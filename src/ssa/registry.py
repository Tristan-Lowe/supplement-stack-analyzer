"""Entity and alias storage. Owns all identity questions for compounds."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.models import (
    Entity,
    EntityAlias,
    EntityKind,
    Evidence,
    Interaction,
    TimingRule,
    UpperLimit,
)
from ssa.normalize import normalize_name


def get_or_create_entity(
    session: Session,
    kind: EntityKind,
    canonical_name: str,
    rxcui: str | None = None,
    unii: str | None = None,
) -> Entity:
    """Fetch an entity by (kind, canonical_name), creating it if absent.

    The canonical name is always registered as an alias so that lookups by
    the canonical form succeed without a special case.
    """
    stmt = select(Entity).where(
        Entity.kind == kind, Entity.canonical_name == canonical_name
    )
    existing = session.scalars(stmt).one_or_none()
    if existing is not None:
        if rxcui and not existing.rxcui:
            existing.rxcui = rxcui
        if unii and not existing.unii:
            existing.unii = unii
        return existing

    entity = Entity(kind=kind, canonical_name=canonical_name, rxcui=rxcui, unii=unii)
    session.add(entity)
    session.flush()
    add_alias(session, entity, canonical_name, source="canonical")
    return entity


def add_alias(
    session: Session, entity: Entity, alias: str, source: str
) -> EntityAlias | None:
    """Attach an alias to an entity. Returns None if this alias already exists."""
    normalized = normalize_name(alias)
    stmt = select(EntityAlias).where(
        EntityAlias.entity_id == entity.id,
        EntityAlias.normalized_alias == normalized,
    )
    if session.scalars(stmt).one_or_none() is not None:
        return None

    record = EntityAlias(
        entity_id=entity.id,
        alias=alias,
        normalized_alias=normalized,
        source=source,
    )
    session.add(record)
    session.flush()
    return record


def find_by_alias(session: Session, raw_name: str) -> list[Entity]:
    """Return every entity whose alias set contains the normalized form of raw_name."""
    normalized = normalize_name(raw_name)
    stmt = (
        select(Entity)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(EntityAlias.normalized_alias == normalized)
        .distinct()
    )
    return list(session.scalars(stmt).all())


def list_aliases(session: Session, entity: Entity) -> list[EntityAlias]:
    stmt = select(EntityAlias).where(EntityAlias.entity_id == entity.id)
    return list(session.scalars(stmt).all())


def all_normalized_aliases(session: Session) -> list[tuple[str, int, EntityKind]]:
    """Every (normalized_alias, entity_id, kind) triple. Used by the resolver.

    Kind travels with the alias because the fuzzy stage treats drugs differently
    from supplements.
    """
    stmt = select(EntityAlias.normalized_alias, EntityAlias.entity_id, Entity.kind).join(
        Entity, Entity.id == EntityAlias.entity_id
    )
    return [(row[0], row[1], row[2]) for row in session.execute(stmt).all()]


def _ordered(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def merge_entities(session: Session, duplicate_id: int, canonical_id: int) -> dict[str, int]:
    """Fold `duplicate_id` into `canonical_id`, moving everything attached to it.

    Duplicates arise when ingestion meets a chemical name ("cholecalciferol")
    before the registry knows it is a synonym of a seeded nutrient ("Vitamin D3"),
    and bootstraps a second entity. The split is harmful: only one of the pair
    carries the UpperLimit row, so a stack naming the other silently skips a
    toxicity ceiling — and the resolver reports Ambiguous instead of answering.

    Interactions are repointed unless that would collide with a pair the canonical
    entity already has, in which case the evidence is moved onto the surviving row
    and the duplicate interaction is dropped. Nothing is discarded silently.
    """
    if duplicate_id == canonical_id:
        raise ValueError("cannot merge an entity into itself")

    moved = {"aliases": 0, "interactions": 0, "evidence": 0, "dropped_interactions": 0}

    canonical = session.get(Entity, canonical_id)
    duplicate = session.get(Entity, duplicate_id)
    if canonical is None or duplicate is None:
        raise ValueError("both entities must exist")

    # Aliases, including the duplicate's own canonical name, so the surface form
    # keeps resolving after the merge.
    existing = {a.normalized_alias for a in list_aliases(session, canonical)}
    for alias in list_aliases(session, duplicate):
        if alias.normalized_alias not in existing:
            session.add(
                EntityAlias(
                    entity_id=canonical_id,
                    alias=alias.alias,
                    normalized_alias=alias.normalized_alias,
                    source=alias.source,
                )
            )
            existing.add(alias.normalized_alias)
            moved["aliases"] += 1
        session.delete(alias)
    session.flush()

    for interaction in session.scalars(
        select(Interaction).where(
            (Interaction.entity_a_id == duplicate_id)
            | (Interaction.entity_b_id == duplicate_id)
        )
    ).all():
        other = (
            interaction.entity_b_id
            if interaction.entity_a_id == duplicate_id
            else interaction.entity_a_id
        )
        if other == canonical_id:
            # Was an interaction between the duplicate and its own canonical form.
            session.delete(interaction)
            moved["dropped_interactions"] += 1
            continue

        low, high = _ordered(canonical_id, other)
        clash = session.scalars(
            select(Interaction).where(
                Interaction.entity_a_id == low,
                Interaction.entity_b_id == high,
                Interaction.id != interaction.id,
            )
        ).one_or_none()

        if clash is None:
            interaction.entity_a_id, interaction.entity_b_id = low, high
            moved["interactions"] += 1
        else:
            for ev in session.scalars(
                select(Evidence).where(Evidence.interaction_id == interaction.id)
            ).all():
                ev.interaction_id = clash.id
                moved["evidence"] += 1
            session.delete(interaction)
            moved["dropped_interactions"] += 1
        session.flush()

    for row in session.scalars(
        select(Interaction).where(Interaction.affected_entity_id == duplicate_id)
    ).all():
        row.affected_entity_id = canonical_id
    session.flush()

    for model in (UpperLimit, TimingRule):
        for row in session.scalars(
            select(model).where(
                (model.entity_id == duplicate_id)
                if model is UpperLimit
                else (
                    (model.entity_a_id == duplicate_id)
                    | (model.entity_b_id == duplicate_id)
                )
            )
        ).all():
            session.delete(row)  # canonical already carries the authoritative rows

    session.delete(duplicate)
    session.commit()
    return moved


def find_nutrient_duplicates(session: Session) -> list[tuple[int, int, str]]:
    """Non-nutrient entities whose name is already a synonym of a seeded nutrient.

    Returns (duplicate_id, canonical_id, name) triples.
    """
    out: list[tuple[int, int, str]] = []
    nutrients = session.scalars(
        select(Entity).where(Entity.kind == EntityKind.NUTRIENT)
    ).all()
    alias_map: dict[str, int] = {}
    for nutrient in nutrients:
        for alias in list_aliases(session, nutrient):
            alias_map.setdefault(alias.normalized_alias, nutrient.id)

    for entity in session.scalars(
        select(Entity).where(Entity.kind != EntityKind.NUTRIENT)
    ).all():
        target = alias_map.get(normalize_name(entity.canonical_name))
        if target is not None and target != entity.id:
            out.append((entity.id, target, entity.canonical_name))
    return out


def reclassify_entities(session: Session) -> list[tuple[str, str, str]]:
    """Re-apply curated kind classification to entities already in the registry.

    Bootstrap originally filed every compound as a DRUG, so supplements ingested
    before classification existed are mislabelled. Returns (name, old, new) for
    each change.
    """
    from ssa.bootstrap import classify_kind  # local: bootstrap imports registry

    changed: list[tuple[str, str, str]] = []
    for entity in session.scalars(select(Entity)).all():
        # A seeded nutrient is authoritative; never downgrade it.
        if entity.kind is EntityKind.NUTRIENT:
            continue
        new_kind = classify_kind(entity.canonical_name)
        if new_kind is not entity.kind:
            changed.append((entity.canonical_name, entity.kind.value, new_kind.value))
            entity.kind = new_kind
    session.commit()
    return changed

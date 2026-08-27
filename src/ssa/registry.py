"""Entity and alias storage. Owns all identity questions for compounds."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.models import Entity, EntityAlias, EntityKind
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


def all_normalized_aliases(session: Session) -> list[tuple[str, int]]:
    """Every (normalized_alias, entity_id) pair. Used by the fuzzy resolver stage."""
    stmt = select(EntityAlias.normalized_alias, EntityAlias.entity_id)
    return [(row[0], row[1]) for row in session.execute(stmt).all()]

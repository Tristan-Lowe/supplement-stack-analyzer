"""Curated supplement registry: the entities users actually type.

The registry otherwise grows only from FDA labels, so a supplement exists only if
some drug label happens to mention it. No label names creatine or ashwagandha,
so those resolved to nothing and a user's stack silently lost items. RxNorm also
names botanicals by preparation ("Garlic Preparation", "St. John's Wort
Extract"), which is not what anyone types or wants to read.

This module seeds clean canonical entities from a hand-maintained CSV and folds
bootstrap-created duplicates into them. A merge happens only when the CSV names
the duplicate explicitly, never by similarity, so every merge is a reviewed
decision rather than an inference.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.models import Entity, EntityAlias, EntityKind, UpperLimit
from ssa.normalize import normalize_name
from ssa.registry import add_alias, get_or_create_entity, merge_entities

SUPPLEMENT_REGISTRY_CSV = "data/supplement_registry.csv"


@dataclass
class CuratedLoadReport:
    created: int = 0
    aliases: int = 0
    merged: list[tuple[str, str]] = field(default_factory=list)


def _names(row: dict[str, str]) -> list[str]:
    aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
    return [row["canonical_name"], *aliases]


def load_supplement_registry(
    session: Session, csv_path: str | Path = SUPPLEMENT_REGISTRY_CSV
) -> CuratedLoadReport:
    """Seed curated supplements and absorb their bootstrap duplicates. Idempotent.

    Raises ValueError, before changing anything for that row, when an alias is
    already owned by an unrelated entity, or when a merge would absorb an entity
    that carries an upper limit. Both are data errors a person must resolve.
    """
    report = CuratedLoadReport()
    rows = csv.DictReader(Path(csv_path).read_text(encoding="utf-8").splitlines())

    for row in rows:
        kind = EntityKind[row["kind"]]
        canonical = row["canonical_name"]
        names = _names(row)
        normalized_names = {normalize_name(n) for n in names}

        existing = session.scalars(
            select(Entity).where(Entity.kind == kind, Entity.canonical_name == canonical)
        ).one_or_none()

        # Entities this row absorbs: those whose own canonical name the CSV lists.
        absorb = [
            e
            for e in session.scalars(select(Entity)).all()
            if normalize_name(e.canonical_name) in normalized_names
            and (existing is None or e.id != existing.id)
        ]
        for entity in absorb:
            has_limit = session.scalars(
                select(UpperLimit).where(UpperLimit.entity_id == entity.id)
            ).first()
            if has_limit is not None:
                raise ValueError(
                    f"{canonical!r} would absorb {entity.canonical_name!r}, which carries "
                    "an upper limit; merge those by hand"
                )

        allowed = {e.id for e in absorb} | ({existing.id} if existing else set())
        owners = session.execute(
            select(EntityAlias.normalized_alias, EntityAlias.entity_id).where(
                EntityAlias.normalized_alias.in_(normalized_names)
            )
        ).all()
        for alias, owner_id in owners:
            if owner_id not in allowed:
                owner = session.get(Entity, owner_id)
                raise ValueError(
                    f"alias {alias!r} for {canonical!r} is already owned by "
                    f"{owner.canonical_name!r}; resolve the conflict in the CSV"
                )

        if existing is None:
            target = get_or_create_entity(session, kind, canonical)
            report.created += 1
        else:
            target = existing
        session.commit()

        for entity in absorb:
            name = entity.canonical_name
            merge_entities(session, entity.id, target.id)
            report.merged.append((name, canonical))

        for name in names[1:]:
            if add_alias(session, target, name, source="curated_registry") is not None:
                report.aliases += 1
        session.commit()

    return report


def renormalize_aliases(session: Session) -> int:
    """Recompute every stored normalized alias under the current normalize_name.

    Keys are computed once, at insert. When normalization improves, old rows keep
    the old key and silently stop matching. Returns the number of rows changed; a
    row whose new key duplicates a sibling on the same entity is removed, since it
    now adds nothing.
    """
    rows = session.scalars(select(EntityAlias).order_by(EntityAlias.id)).all()
    new_key = {row.id: normalize_name(row.alias) for row in rows}

    # Keep one row per (entity, key), preferring a row whose stored key is already
    # correct. Deletes are flushed BEFORE any key is rewritten: rewriting first would
    # momentarily duplicate a key and violate the unique constraint.
    keep: dict[tuple[int, str], EntityAlias] = {}
    for row in rows:
        slot = (row.entity_id, new_key[row.id])
        current = keep.get(slot)
        if current is None or (
            row.normalized_alias == new_key[row.id]
            and current.normalized_alias != new_key[current.id]
        ):
            keep[slot] = row
    survivors = {row.id for row in keep.values()}

    changed = 0
    for row in rows:
        if row.id not in survivors:
            session.delete(row)
            changed += 1
    session.flush()

    for row in rows:
        if row.id in survivors and row.normalized_alias != new_key[row.id]:
            row.normalized_alias = new_key[row.id]
            changed += 1
    session.commit()
    return changed

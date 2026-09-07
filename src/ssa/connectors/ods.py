"""Seed tolerable upper intake levels from the curated NIH ODS CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy import select as _select
from sqlalchemy.orm import Session

from ssa.models import Entity, EntityKind, UpperLimit
from ssa.registry import add_alias, get_or_create_entity


def load_upper_limits(session: Session, csv_path: str | Path) -> int:
    """Load upper limits into the database. Returns the number of new rows created.

    Idempotent: re-running adds nothing and returns 0.
    """
    created = 0
    rows = csv.DictReader(Path(csv_path).read_text(encoding="utf-8").splitlines())

    for row in rows:
        entity = get_or_create_entity(session, EntityKind.NUTRIENT, row["canonical_name"])
        existing = session.scalars(
            select(UpperLimit).where(
                UpperLimit.entity_id == entity.id,
                UpperLimit.population == row["population"],
            )
        ).one_or_none()
        if existing is not None:
            continue

        session.add(
            UpperLimit(
                entity_id=entity.id,
                amount=float(row["amount"]),
                unit=row["unit"],
                population=row["population"],
                basis=row["basis"],
                source_url=row["source_url"],
            )
        )
        created += 1

    session.commit()
    return created


def load_nutrient_synonyms(session: Session, csv_path: str | Path) -> int:
    """Register chemical and salt-form synonyms as aliases on seeded nutrients.

    Without these, ingestion meets "cholecalciferol" in an FDA label, fails to
    resolve it, and bootstraps a *new* DRUG entity — duplicating the seeded
    Vitamin D3. That split is not cosmetic: only the seeded nutrient carries an
    UpperLimit row, so a user entering the chemical name would silently get no
    toxicity-ceiling check at all.

    Returns the number of new aliases created. Idempotent.
    """
    created = 0
    rows = csv.DictReader(Path(csv_path).read_text(encoding="utf-8").splitlines())

    for row in rows:
        entity = session.scalars(
            _select(Entity).where(
                Entity.kind == EntityKind.NUTRIENT,
                Entity.canonical_name == row["canonical_name"],
            )
        ).one_or_none()
        if entity is None:
            # Upper limits must be seeded first; a synonym with no nutrient to
            # attach to is a data error worth surfacing, not silently skipping.
            raise ValueError(
                f"no seeded nutrient named {row['canonical_name']!r} for synonym "
                f"{row['synonym']!r} — load upper limits first"
            )
        if add_alias(session, entity, row["synonym"], source="curated_synonym") is not None:
            created += 1

    session.commit()
    return created

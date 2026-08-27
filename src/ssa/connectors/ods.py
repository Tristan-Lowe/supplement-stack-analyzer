"""Seed tolerable upper intake levels from the curated NIH ODS CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.models import EntityKind, UpperLimit
from ssa.registry import get_or_create_entity


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

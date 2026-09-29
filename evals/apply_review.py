"""Apply a review decisions CSV to the database, all-or-nothing.

Every row is validated before anything is written: the interaction must exist,
the affected entity must be one side of its pair, and a direction ending in
"_of_b" must name its affected entity once the decision is applied.

    python -m evals.apply_review data/reviews/2026-09-29-review.csv "reviewer name"
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from sqlalchemy import select

from ssa.db import make_engine, make_session_factory
from ssa.models import Entity, EvidenceGrade, Interaction, Severity
from ssa.review import approve, reject


def main(argv: list[str]) -> int:
    path, reviewer = argv[0], argv[1]
    rows = list(csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()))
    session = make_session_factory(make_engine())()
    by_name = {e.canonical_name: e.id for e in session.scalars(select(Entity)).all()}

    errors: list[str] = []
    for row in rows:
        interaction = session.get(Interaction, int(row["id"]))
        if interaction is None:
            errors.append(f"#{row['id']}: no such interaction")
            continue
        if row["action"] not in ("approve", "reject"):
            errors.append(f"#{row['id']}: bad action {row['action']!r}")
        affected = row["affected"].strip()
        if affected:
            affected_id = by_name.get(affected)
            if affected_id not in (interaction.entity_a_id, interaction.entity_b_id):
                errors.append(f"#{row['id']}: {affected!r} is not one side of the pair")
        final_direction = row["direction"].strip() or interaction.direction
        final_affected = affected or interaction.affected_entity_id
        if (
            row["action"] == "approve"
            and final_direction.endswith("_of_b")
            and not final_affected
        ):
            errors.append(f"#{row['id']}: {final_direction} with no affected entity")

    if errors:
        print("Nothing applied:")
        for error in errors:
            print(" ", error)
        return 1

    for row in rows:
        iid = int(row["id"])
        note = row["note"].strip() or None
        if row["action"] == "reject":
            reject(session, iid, reviewer=reviewer, note=note)
            continue
        approve(
            session,
            iid,
            reviewer=reviewer,
            note=note,
            severity=Severity(row["severity"]) if row["severity"].strip() else None,
            evidence_grade=(
                EvidenceGrade(row["evidence"]) if row["evidence"].strip() else None
            ),
            direction=row["direction"].strip() or None,
            affected_entity_id=by_name[row["affected"].strip()]
            if row["affected"].strip()
            else None,
        )
    print(f"Applied {len(rows)} decisions as {reviewer!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

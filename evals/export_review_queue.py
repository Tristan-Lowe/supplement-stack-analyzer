"""Print every interaction awaiting review, with its quotes, for a reviewer to read.

    python -m evals.export_review_queue > queue.txt

Decisions go in a CSV under data/reviews/ and are applied with evals.apply_review,
which validates every row before writing anything.
"""

from __future__ import annotations

import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ssa.db import make_engine, make_session_factory
from ssa.models import ConflictRecord, Entity, Interaction, InteractionStatus


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    session = make_session_factory(make_engine())()
    rows = session.scalars(
        select(Interaction)
        .options(selectinload(Interaction.evidence))
        .where(Interaction.status == InteractionStatus.PENDING_REVIEW)
        .order_by(Interaction.id)
    ).all()
    for i in rows:
        a = session.get(Entity, i.entity_a_id)
        b = session.get(Entity, i.entity_b_id)
        affected = session.get(Entity, i.affected_entity_id) if i.affected_entity_id else None
        conflicts = session.scalars(
            select(ConflictRecord).where(ConflictRecord.interaction_id == i.id)
        ).all()
        print(
            f"#{i.id} {a.canonical_name} [{a.kind.value}] + {b.canonical_name} [{b.kind.value}]"
            f" | {i.severity.value}/{i.evidence_grade.value} | {i.direction}"
            f"{' -> ' + affected.canonical_name if affected else ''} | conflicts {len(conflicts)}"
        )
        print(f"   M: {i.mechanism}")
        for span in sorted({e.span for e in i.evidence})[:3]:
            print(f"   S: {span[:400]}")
    print(f"\n{len(rows)} pending")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

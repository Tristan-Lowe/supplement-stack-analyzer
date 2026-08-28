"""Cumulative intake against tolerable upper intake levels.

Unit conversion is deliberately not attempted. When a dose is reported in a unit
that differs from the published limit, the check is skipped rather than guessed —
a wrong conversion here would produce a false all-clear on a toxicity ceiling.
Unit conversion is a plan-two task with its own tests.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.analyze.findings import Citation, Finding, FindingKind, Tier
from ssa.analyze.redundancy import ResolvedDose
from ssa.models import Entity, Severity, UpperLimit


def check_upper_limits(session: Session, doses: list[ResolvedDose]) -> list[Finding]:
    """Sum each entity's daily intake and compare against its published upper limit."""
    by_entity: dict[int, list[ResolvedDose]] = defaultdict(list)
    for dose in doses:
        by_entity[dose.entity_id].append(dose)

    findings: list[Finding] = []

    for entity_id, contributions in by_entity.items():
        limit = session.scalars(
            select(UpperLimit).where(
                UpperLimit.entity_id == entity_id,
                UpperLimit.population == "adult",
            )
        ).one_or_none()
        if limit is None:
            continue

        usable = [
            c for c in contributions
            if c.amount is not None and c.unit is not None and c.unit == limit.unit
        ]
        if not usable or len(usable) != len(contributions):
            continue

        total = sum(c.amount for c in usable)
        if total <= limit.amount:
            continue

        entity = session.get(Entity, entity_id)
        name = entity.canonical_name if entity else f"entity {entity_id}"
        labels = ", ".join(c.source_label for c in usable)
        total_text = f"{total:g}"
        limit_text = f"{limit.amount:g}"

        findings.append(
            Finding(
                kind=FindingKind.UPPER_LIMIT,
                severity=Severity.MAJOR,
                title=f"{name} exceeds its tolerable upper intake level",
                detail=(
                    f"Your total {name} intake is {total_text} {limit.unit} per day "
                    f"from {labels}, above the published adult upper limit of "
                    f"{limit_text} {limit.unit}. {limit.basis}"
                ),
                entity_ids=[entity_id],
                citations=[
                    Citation(source="nih_ods", source_url=limit.source_url, span=limit.basis)
                ],
                confidence=1.0,
                tier=Tier.GRAPH,
            )
        )

    return findings

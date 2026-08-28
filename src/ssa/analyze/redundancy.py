"""Redundancy check: the same compound arriving from more than one product.

This is the check that catches a multivitamin overlapping single-ingredient
products — the most common real-world path to an unintended cumulative dose.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ssa.analyze.findings import Finding, FindingKind, Tier
from ssa.models import Entity, Severity


@dataclass(frozen=True)
class ResolvedDose:
    """One resolved compound with its amount and the product it came from."""

    entity_id: int
    amount: float | None
    unit: str | None
    source_label: str


def check_redundancy(session: Session, doses: list[ResolvedDose]) -> list[Finding]:
    """Flag any entity supplied by two or more products.

    When every contribution shares a unit, the cumulative total is reported.
    When units differ, the overlap is still flagged but no total is invented.
    """
    by_entity: dict[int, list[ResolvedDose]] = defaultdict(list)
    for dose in doses:
        by_entity[dose.entity_id].append(dose)

    findings: list[Finding] = []

    for entity_id, contributions in by_entity.items():
        if len(contributions) < 2:
            continue

        entity = session.get(Entity, entity_id)
        name = entity.canonical_name if entity else f"entity {entity_id}"
        labels = ", ".join(c.source_label for c in contributions)

        units = {c.unit for c in contributions if c.unit is not None}
        amounts = [c.amount for c in contributions if c.amount is not None]

        lead = f"{name} appears in {len(contributions)} products ({labels}), "

        if len(units) == 1 and len(amounts) == len(contributions):
            unit = units.pop()
            detail = lead + f"totalling {sum(amounts):g} {unit} per day."
        elif len(units) > 1:
            detail = lead + "reported in different units, so no cumulative total is shown."
        else:
            # Units agree (or are absent) but at least one product states no dose.
            # Saying "different units" here would be factually false about the
            # user's own stack, which costs trust for no benefit.
            missing = len(contributions) - len(amounts)
            detail = (
                lead
                + f"but {missing} of them state no dose, so no cumulative total is shown."
            )

        findings.append(
            Finding(
                kind=FindingKind.REDUNDANCY,
                severity=Severity.MINOR,
                title=f"{name} appears more than once",
                detail=detail,
                entity_ids=[entity_id],
                citations=[],
                confidence=1.0,
                tier=Tier.GRAPH,
            )
        )

    return findings

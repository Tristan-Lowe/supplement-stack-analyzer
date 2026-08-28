"""Cumulative intake against tolerable upper intake levels.

Two rules govern this check.

**Never guess a unit.** When a dose is reported in a unit that differs from the
published limit, it is not converted. A wrong mcg-to-IU conversion would produce
a false all-clear on a toxicity ceiling. Unit conversion is a plan-two task with
its own tests.

**Never go silent.** An entity whose doses cannot all be measured is still
assessed on the portion that can be, and the shortfall is reported. If the
measurable portion alone already exceeds the ceiling, that is a certain breach
regardless of what could not be measured. If it does not, the user is told the
check was incomplete rather than being shown nothing — silence in a safety tool
reads as an all-clear.
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
            c
            for c in contributions
            if c.amount is not None and c.unit is not None and c.unit == limit.unit
        ]
        unusable = [c for c in contributions if c not in usable]

        entity = session.get(Entity, entity_id)
        name = entity.canonical_name if entity else f"entity {entity_id}"
        citation = Citation(source="nih_ods", source_url=limit.source_url, span=limit.basis)

        total = sum(c.amount for c in usable) if usable else 0.0
        limit_text = f"{limit.amount:g}"

        if usable and total > limit.amount:
            labels = ", ".join(c.source_label for c in usable)
            qualifier = (
                f" This counts only the {len(usable)} of {len(contributions)} sources we could "
                f"measure, so your real total is higher."
                if unusable
                else ""
            )
            findings.append(
                Finding(
                    kind=FindingKind.UPPER_LIMIT,
                    severity=Severity.MAJOR,
                    title=f"{name} exceeds its tolerable upper intake level",
                    detail=(
                        f"Your total {name} intake is {total:g} {limit.unit} per day "
                        f"from {labels}, above the published adult upper limit of "
                        f"{limit_text} {limit.unit}.{qualifier} {limit.basis}"
                    ),
                    entity_ids=[entity_id],
                    citations=[citation],
                    confidence=1.0,
                    tier=Tier.GRAPH,
                )
            )
            continue

        if unusable:
            # Under the ceiling on what we could measure — but we could not measure
            # everything, so we must not imply the total is within the limit.
            missing = ", ".join(c.source_label for c in unusable)
            measured = (
                f"The {len(usable)} source(s) we could measure total {total:g} {limit.unit}, "
                f"against a limit of {limit_text} {limit.unit}. "
                if usable
                else ""
            )
            findings.append(
                Finding(
                    kind=FindingKind.UNRESOLVED,
                    severity=Severity.MINOR,
                    title=f"{name} intake could not be fully assessed",
                    detail=(
                        f"{measured}We could not read a comparable dose for: {missing}. "
                        f"{name} has a published upper limit of {limit_text} {limit.unit}, "
                        f"so the unmeasured amount matters. {limit.basis}"
                    ),
                    entity_ids=[entity_id],
                    citations=[citation],
                    confidence=1.0,
                    tier=Tier.GRAPH,
                )
            )

    return findings

"""Separation requirements between compounds.

Timing rules are stored separately from interaction edges because they are not
pairwise interaction claims — they are actionable scheduling guidance that stands
even when the underlying interaction is well tolerated.
"""

from __future__ import annotations

from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.analyze.findings import Citation, Finding, FindingKind, Tier
from ssa.models import Entity, Severity, TimingRule


def _ordered_pair(entity_a_id: int, entity_b_id: int) -> tuple[int, int]:
    return (
        (entity_a_id, entity_b_id) if entity_a_id < entity_b_id else (entity_b_id, entity_a_id)
    )


def seed_timing_rule(
    session: Session,
    entity_a_id: int,
    entity_b_id: int,
    separation_hours: float,
    note: str,
    source_url: str,
) -> TimingRule:
    """Insert a timing rule, storing the pair in stable order. Idempotent."""
    low_id, high_id = _ordered_pair(entity_a_id, entity_b_id)

    existing = session.scalars(
        select(TimingRule).where(
            TimingRule.entity_a_id == low_id,
            TimingRule.entity_b_id == high_id,
        )
    ).one_or_none()
    if existing is not None:
        return existing

    rule = TimingRule(
        entity_a_id=low_id,
        entity_b_id=high_id,
        separation_hours=separation_hours,
        note=note,
        source_url=source_url,
    )
    session.add(rule)
    session.commit()
    return rule


def check_timing(session: Session, entity_ids: list[int]) -> list[Finding]:
    """Return a finding for every pair in the stack that has a separation rule."""
    unique_ids = sorted(set(entity_ids))
    if len(unique_ids) < 2:
        return []

    findings: list[Finding] = []

    for low_id, high_id in combinations(unique_ids, 2):
        rule = session.scalars(
            select(TimingRule).where(
                TimingRule.entity_a_id == low_id,
                TimingRule.entity_b_id == high_id,
            )
        ).one_or_none()
        if rule is None:
            continue

        name_a = session.get(Entity, low_id).canonical_name
        name_b = session.get(Entity, high_id).canonical_name
        hours = f"{rule.separation_hours:g}"

        findings.append(
            Finding(
                kind=FindingKind.TIMING,
                severity=Severity.MODERATE,
                title=f"Separate {name_a} and {name_b} by {hours} hours",
                detail=rule.note,
                entity_ids=[low_id, high_id],
                citations=[Citation(source="label", source_url=rule.source_url, span=rule.note)],
                confidence=1.0,
                tier=Tier.GRAPH,
            )
        )

    return findings

"""Pairwise interaction lookup. Deterministic database query — no LLM."""

from __future__ import annotations

from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ssa.analyze.findings import Citation, Finding, FindingKind, Tier
from ssa.models import Entity, Interaction, InteractionStatus


def check_pairwise(session: Session, entity_ids: list[int]) -> list[Finding]:
    """Look up every pair of resolved entities against published interaction edges.

    Only PUBLISHED interactions are returned. A moderate-or-above edge sitting in
    PENDING_REVIEW is withheld deliberately — an unreviewed high-severity claim is
    not shown to a user.
    """
    unique_ids = sorted(set(entity_ids))
    if len(unique_ids) < 2:
        return []

    findings: list[Finding] = []

    for low_id, high_id in combinations(unique_ids, 2):
        interaction = session.scalars(
            select(Interaction)
            .options(selectinload(Interaction.evidence))
            .where(
                Interaction.entity_a_id == low_id,
                Interaction.entity_b_id == high_id,
                Interaction.status == InteractionStatus.PUBLISHED,
            )
        ).one_or_none()
        if interaction is None:
            continue

        name_a = session.get(Entity, low_id).canonical_name
        name_b = session.get(Entity, high_id).canonical_name

        findings.append(
            Finding(
                kind=FindingKind.INTERACTION,
                severity=interaction.severity,
                title=f"{name_a} + {name_b}",
                detail=interaction.mechanism,
                entity_ids=[low_id, high_id],
                citations=[
                    Citation(source=e.source, source_url=e.source_url, span=e.span)
                    for e in interaction.evidence
                ],
                confidence=interaction.confidence,
                tier=Tier.GRAPH,
            )
        )

    return findings

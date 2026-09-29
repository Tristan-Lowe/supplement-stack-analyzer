"""Pairwise interaction lookup. Deterministic database query — no LLM."""

from __future__ import annotations

from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ssa.analyze.findings import Citation, Finding, FindingKind, Tier
from ssa.models import SEVERITY_RANK, Entity, Interaction, InteractionStatus
from ssa.registry import classes_of


def check_pairwise(session: Session, entity_ids: list[int]) -> list[Finding]:
    """Look up every pair of resolved entities against published interaction edges.

    Only PUBLISHED interactions are returned. A moderate-or-above edge sitting in
    PENDING_REVIEW is withheld deliberately — an unreviewed high-severity claim is
    not shown to a user.

    A pair is also checked through the drug classes each side belongs to: a label
    warning about "NSAIDs" applies to a user taking ibuprofen. A direct edge between
    the two compounds always wins; otherwise the most severe class edge is shown,
    and the finding says which class it came through.
    """
    unique_ids = sorted(set(entity_ids))
    if len(unique_ids) < 2:
        return []

    memberships = classes_of(session, unique_ids)
    all_ids = set(unique_ids) | {c for cs in memberships.values() for c in cs}
    edges = {
        (i.entity_a_id, i.entity_b_id): i
        for i in session.scalars(
            select(Interaction)
            .options(selectinload(Interaction.evidence))
            .where(
                Interaction.entity_a_id.in_(all_ids),
                Interaction.entity_b_id.in_(all_ids),
                Interaction.status == InteractionStatus.PUBLISHED,
            )
        ).all()
    }

    def edge(a: int, b: int) -> Interaction | None:
        return edges.get((a, b) if a < b else (b, a))

    findings: list[Finding] = []
    for x, y in combinations(unique_ids, 2):
        chosen = edge(x, y)
        via: list[int] = []
        if chosen is None:
            best: tuple[Interaction, list[int]] | None = None
            for side_x in [x, *memberships[x]]:
                for side_y in [y, *memberships[y]]:
                    if (side_x, side_y) == (x, y) or side_x == side_y:
                        continue
                    candidate = edge(side_x, side_y)
                    if candidate is None:
                        continue
                    classes = [c for c in (side_x, side_y) if c not in (x, y)]
                    if best is None or (
                        SEVERITY_RANK[candidate.severity],
                        candidate.confidence,
                    ) > (SEVERITY_RANK[best[0].severity], best[0].confidence):
                        best = (candidate, classes)
            if best is None:
                continue
            chosen, via = best

        name_x = session.get(Entity, x).canonical_name
        name_y = session.get(Entity, y).canonical_name
        detail = chosen.mechanism
        if via:
            class_names = " and ".join(session.get(Entity, c).canonical_name for c in via)
            detail += (
                f" The label states this for {class_names} as a class; "
                f"it applies here through class membership."
            )

        findings.append(
            Finding(
                kind=FindingKind.INTERACTION,
                severity=chosen.severity,
                title=f"{name_x} + {name_y}",
                detail=detail,
                entity_ids=[x, y],
                citations=[
                    Citation(source=e.source, source_url=e.source_url, span=e.span)
                    for e in chosen.evidence
                ],
                confidence=chosen.confidence,
                tier=Tier.GRAPH,
            )
        )

    return findings

"""Validation gates: dedup, merge, conflict detection, confidence scoring.

Two rules matter here. Pairs are stored in a stable (lower id, higher id) order so
one pair is one row regardless of which direction a source described it. And when
sources disagree, the disagreement is recorded rather than averaged — the product
shows the conflict and both citations.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.models import (
    REVIEW_REQUIRED_AT_OR_ABOVE,
    SEVERITY_RANK,
    ConflictRecord,
    Evidence,
    EvidenceGrade,
    Interaction,
    InteractionStatus,
    Severity,
)

BASE_CONFIDENCE = 0.6
AGREEMENT_BONUS = 0.15
MAX_CONFIDENCE = 0.99


def _ordered_pair(entity_a_id: int, entity_b_id: int) -> tuple[int, int]:
    return (
        (entity_a_id, entity_b_id) if entity_a_id < entity_b_id else (entity_b_id, entity_a_id)
    )


def _initial_status(severity: Severity) -> InteractionStatus:
    if SEVERITY_RANK[severity] >= REVIEW_REQUIRED_AT_OR_ABOVE:
        return InteractionStatus.PENDING_REVIEW
    return InteractionStatus.PUBLISHED


def merge_triple(
    session: Session,
    entity_a_id: int,
    entity_b_id: int,
    mechanism: str,
    direction: str,
    severity: Severity,
    evidence_grade: EvidenceGrade,
    span: str,
    source: str,
    source_url: str,
    pipeline_run_id: int | None = None,
) -> Interaction:
    """Insert or merge one verified triple, attaching its evidence.

    New pair: created with base confidence, and held for review when severity is
    moderate or above. Existing pair: evidence is appended; agreement raises
    confidence; disagreement on severity or direction writes a ConflictRecord and
    keeps the more severe value, because under-reporting a risk is the failure that
    hurts someone.
    """
    low_id, high_id = _ordered_pair(entity_a_id, entity_b_id)

    existing = session.scalars(
        select(Interaction).where(
            Interaction.entity_a_id == low_id,
            Interaction.entity_b_id == high_id,
        )
    ).one_or_none()

    if existing is None:
        interaction = Interaction(
            entity_a_id=low_id,
            entity_b_id=high_id,
            mechanism=mechanism,
            direction=direction,
            severity=severity,
            evidence_grade=evidence_grade,
            confidence=BASE_CONFIDENCE,
            status=_initial_status(severity),
            pipeline_run_id=pipeline_run_id,
        )
        session.add(interaction)
        session.flush()
    else:
        interaction = existing
        agreed = True

        if interaction.severity is not severity:
            agreed = False
            session.add(
                ConflictRecord(
                    interaction_id=interaction.id,
                    field="severity",
                    existing_value=interaction.severity.value,
                    incoming_value=severity.value,
                    incoming_source_url=source_url,
                )
            )
            if SEVERITY_RANK[severity] > SEVERITY_RANK[interaction.severity]:
                interaction.severity = severity
                interaction.status = _initial_status(severity)

        if interaction.direction != direction:
            agreed = False
            session.add(
                ConflictRecord(
                    interaction_id=interaction.id,
                    field="direction",
                    existing_value=interaction.direction,
                    incoming_value=direction,
                    incoming_source_url=source_url,
                )
            )

        if agreed:
            interaction.confidence = min(
                interaction.confidence + AGREEMENT_BONUS, MAX_CONFIDENCE
            )

    session.add(
        Evidence(
            interaction_id=interaction.id,
            source=source,
            source_url=source_url,
            span=span,
        )
    )
    session.commit()
    return interaction

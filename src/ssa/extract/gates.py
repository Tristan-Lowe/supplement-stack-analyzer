"""Validation gates: dedup, merge, conflict detection, confidence scoring.

Four rules matter here.

**No span, no triple.** `merge_triple` verifies the span against the source text
itself rather than trusting its caller. The pipeline verifies and quarantines
before calling, so reaching the raise below means a programming error — but the
system's governing invariant should not depend on every future caller
remembering it.

**One pair, one row.** Pairs are stored in a stable (lower id, higher id) order
so a pair is one row regardless of which direction a source described it.

**Disagreement is recorded, never averaged.** When sources conflict on severity,
direction, or evidence grade, a ConflictRecord is written and the product shows
the conflict with both citations.

**Confidence measures independent corroboration.** Agreement raises confidence
only when it arrives with span text not already on record. A URL check alone is
not enough: generic drugs carry the same FDA-mandated interaction wording across
every manufacturer, so one sentence can reach us under five distinct label ids.
Counting those as five independent sources would be self-corroboration wearing a
disguise, in the number used to rank findings.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.extract.schema import VALID_DIRECTIONS
from ssa.extract.verify import collapse_for_comparison, span_appears_in
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


class UnverifiedSpanError(ValueError):
    """Raised when a triple reaches the gate with a span absent from its source."""


class InvalidDirectionError(ValueError):
    """Raised when a triple carries a direction outside the controlled vocabulary."""


def _ordered_pair(entity_a_id: int, entity_b_id: int) -> tuple[int, int]:
    return (
        (entity_a_id, entity_b_id) if entity_a_id < entity_b_id else (entity_b_id, entity_a_id)
    )


def affected_side(direction: str, entity_b_id: int) -> int | None:
    """The entity a direction acts on, fixed BEFORE the pair is reordered.

    The model writes "decreases_absorption_of_b" about its own (a, b). Storage
    sorts the pair by id, so for about half of all rows the stored b is the model's
    a. Recording the affected entity by id is what keeps the claim true.
    """
    return entity_b_id if direction.endswith("_of_b") else None


def _direction_label(direction: str, affected_id: int | None) -> str:
    return direction if affected_id is None else f"{direction} (entity {affected_id})"


def _initial_status(severity: Severity) -> InteractionStatus:
    if SEVERITY_RANK[severity] >= REVIEW_REQUIRED_AT_OR_ABOVE:
        return InteractionStatus.PENDING_REVIEW
    return InteractionStatus.PUBLISHED


def _is_new_evidence(session: Session, interaction_id: int, source_url: str, span: str) -> bool:
    """True only when BOTH the source and the span content are unseen for this pair.

    Identical prose reaching us from two URLs is copied text, not two independent
    observations — the case that matters in practice, since generic labels
    replicate the same wording across manufacturers.
    """
    existing = session.scalars(
        select(Evidence).where(Evidence.interaction_id == interaction_id)
    ).all()
    normalized = collapse_for_comparison(span)
    for row in existing:
        if row.source_url == source_url or collapse_for_comparison(row.span) == normalized:
            return False
    return True


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
    source_text: str,
    pipeline_run_id: int | None = None,
) -> Interaction:
    """Insert or merge one triple, verifying its span and attaching its evidence.

    Raises UnverifiedSpanError when `span` does not appear in `source_text`.

    New pair: created with base confidence, held for review when severity is
    moderate or above. Existing pair: evidence is appended; corroboration from a
    *new* source raises confidence; disagreement writes a ConflictRecord and keeps
    the more severe value, because under-reporting a risk is the failure that hurts
    someone.

    A row a human has REJECTED is never resurrected by a later ingest. Its evidence
    and conflicts still accrue so the decision can be revisited deliberately, but
    the status stays put.
    """
    if direction not in VALID_DIRECTIONS:
        raise InvalidDirectionError(
            f"{direction!r} is not one of {sorted(VALID_DIRECTIONS)}"
        )

    if not span_appears_in(span, source_text):
        raise UnverifiedSpanError(
            f"span not found in source ({source_url}): {span[:80]!r}"
        )

    affected_id = affected_side(direction, entity_b_id)
    low_id, high_id = _ordered_pair(entity_a_id, entity_b_id)

    interaction = session.scalars(
        select(Interaction).where(
            Interaction.entity_a_id == low_id,
            Interaction.entity_b_id == high_id,
        )
    ).one_or_none()

    if interaction is None:
        interaction = Interaction(
            entity_a_id=low_id,
            entity_b_id=high_id,
            mechanism=mechanism,
            direction=direction,
            affected_entity_id=affected_id,
            severity=severity,
            evidence_grade=evidence_grade,
            confidence=BASE_CONFIDENCE,
            status=_initial_status(severity),
            pipeline_run_id=pipeline_run_id,
        )
        session.add(interaction)
        session.flush()
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

    # Corroboration only counts from a source we have not already recorded.
    # Without this, re-ingesting one document walks confidence 0.6 -> 0.75 -> 0.90,
    # presenting self-agreement as agreement between sources.
    is_new_source = _is_new_evidence(session, interaction.id, source_url, span)
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
            # Ingestion never overwrites a status a person set. A row that is
            # already PUBLISHED or REJECTED has been decided; silently flipping an
            # approved interaction back to PENDING_REVIEW would withdraw it from
            # users with no notice, which is the same failure as resurrecting a
            # rejected one. The escalation is preserved in the ConflictRecord above
            # so a reviewer can act on it deliberately.
            if interaction.status is InteractionStatus.PENDING_REVIEW:
                interaction.status = _initial_status(severity)

    # Same wording about opposite compounds is a disagreement, not agreement.
    if (interaction.direction, interaction.affected_entity_id) != (direction, affected_id):
        agreed = False
        session.add(
            ConflictRecord(
                interaction_id=interaction.id,
                field="direction",
                existing_value=_direction_label(
                    interaction.direction, interaction.affected_entity_id
                ),
                incoming_value=_direction_label(direction, affected_id),
                incoming_source_url=source_url,
            )
        )

    if interaction.evidence_grade is not evidence_grade:
        agreed = False
        session.add(
            ConflictRecord(
                interaction_id=interaction.id,
                field="evidence_grade",
                existing_value=interaction.evidence_grade.value,
                incoming_value=evidence_grade.value,
                incoming_source_url=source_url,
            )
        )

    if agreed and is_new_source:
        interaction.confidence = min(interaction.confidence + AGREEMENT_BONUS, MAX_CONFIDENCE)

    if is_new_source:
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

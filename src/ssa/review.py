"""Human review queue for interactions held at moderate-or-above severity.

Extraction proposes; a person decides. Everything at moderate severity or above
lands in PENDING_REVIEW and is withheld from users until someone approves it, so
this queue is the only path from an extracted claim to something a user can see.

Approving or rejecting is a deliberate act with a record. That audit trail is
also what a clinic buys: evidence of who accepted which claim, and when.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ssa.models import (
    Entity,
    EvidenceGrade,
    Interaction,
    InteractionStatus,
    Severity,
    utcnow,
)


@dataclass(frozen=True)
class PendingItem:
    interaction_id: int
    pair: str
    severity: str
    evidence_grade: str
    confidence: float
    mechanism: str
    spans: list[str]
    sources: list[str]


def list_pending(session: Session, limit: int = 50) -> list[PendingItem]:
    """Interactions awaiting a decision, most severe and best-supported first."""
    rows = session.scalars(
        select(Interaction)
        .options(selectinload(Interaction.evidence))
        .where(Interaction.status == InteractionStatus.PENDING_REVIEW)
        .limit(limit)
    ).all()

    items: list[PendingItem] = []
    for row in rows:
        a = session.get(Entity, row.entity_a_id)
        b = session.get(Entity, row.entity_b_id)
        items.append(
            PendingItem(
                interaction_id=row.id,
                pair=f"{a.canonical_name} + {b.canonical_name}",
                severity=row.severity.value,
                evidence_grade=row.evidence_grade.value,
                confidence=row.confidence,
                mechanism=row.mechanism,
                spans=[e.span for e in row.evidence],
                sources=[e.source_url for e in row.evidence],
            )
        )
    return sorted(items, key=lambda i: (-i.confidence, i.interaction_id))


def _set_status(
    session: Session,
    interaction_id: int,
    status: InteractionStatus,
    reviewer: str,
    note: str | None,
) -> Interaction | None:
    interaction = session.get(Interaction, interaction_id)
    if interaction is None:
        return None
    interaction.status = status
    interaction.reviewed_by = reviewer
    interaction.reviewed_at = utcnow()
    interaction.review_note = note
    session.commit()
    return interaction


def approve(
    session: Session,
    interaction_id: int,
    reviewer: str = "unspecified",
    note: str | None = None,
    severity: Severity | None = None,
    evidence_grade: EvidenceGrade | None = None,
    direction: str | None = None,
    affected_entity_id: int | None = None,
) -> Interaction | None:
    """Publish an interaction so the analysis engine will surface it.

    The reviewer may correct severity or evidence grade on the way through. Those
    are the fields the model is least reliable on (it contradicts itself across
    label sections), so correcting them is the review's main job. Every correction
    is written into the note with its original value.
    """
    interaction = session.get(Interaction, interaction_id)
    if interaction is None:
        return None

    corrections: list[str] = []
    if severity is not None and severity is not interaction.severity:
        corrections.append(f"severity {interaction.severity.value} -> {severity.value}")
        interaction.severity = severity
    if evidence_grade is not None and evidence_grade is not interaction.evidence_grade:
        corrections.append(
            f"evidence {interaction.evidence_grade.value} -> {evidence_grade.value}"
        )
        interaction.evidence_grade = evidence_grade
    if direction is not None and direction != interaction.direction:
        corrections.append(f"direction {interaction.direction} -> {direction}")
        interaction.direction = direction
    if affected_entity_id is not None and affected_entity_id != interaction.affected_entity_id:
        if affected_entity_id not in (interaction.entity_a_id, interaction.entity_b_id):
            raise ValueError("affected entity must be one side of the pair")
        corrections.append(
            f"affected {interaction.affected_entity_id} -> {affected_entity_id}"
        )
        interaction.affected_entity_id = affected_entity_id

    full_note = "; ".join(part for part in [note, *corrections] if part) or None
    return _set_status(
        session, interaction_id, InteractionStatus.PUBLISHED, reviewer, full_note
    )


def reject(
    session: Session,
    interaction_id: int,
    reviewer: str = "unspecified",
    note: str | None = None,
) -> Interaction | None:
    """Reject an interaction. merge_triple will not resurrect it on later ingests."""
    return _set_status(session, interaction_id, InteractionStatus.REJECTED, reviewer, note)

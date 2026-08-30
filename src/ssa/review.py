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

from ssa.models import Entity, Interaction, InteractionStatus


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
    session: Session, interaction_id: int, status: InteractionStatus
) -> Interaction | None:
    interaction = session.get(Interaction, interaction_id)
    if interaction is None:
        return None
    interaction.status = status
    session.commit()
    return interaction


def approve(session: Session, interaction_id: int) -> Interaction | None:
    """Publish an interaction so the analysis engine will surface it."""
    return _set_status(session, interaction_id, InteractionStatus.PUBLISHED)


def reject(session: Session, interaction_id: int) -> Interaction | None:
    """Reject an interaction. merge_triple will not resurrect it on later ingests."""
    return _set_status(session, interaction_id, InteractionStatus.REJECTED)

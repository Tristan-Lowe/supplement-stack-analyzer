"""Human review queue. Extraction proposes; a person decides."""

from sqlalchemy import select

from ssa.analyze.pairwise import check_pairwise
from ssa.extract.gates import merge_triple
from ssa.models import EntityKind, EvidenceGrade, Interaction, InteractionStatus, Severity
from ssa.registry import get_or_create_entity
from ssa.review import approve, list_pending, reject

SOURCE = "Calcium carbonate may bind levothyroxine and reduce its absorption."


def seed_pending(session, severity=Severity.MODERATE):
    a = get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    b = get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()
    interaction = merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id,
        mechanism="Binding reduces absorption.", direction="decreases_absorption_of_b",
        severity=severity, evidence_grade=EvidenceGrade.B, span=SOURCE,
        source="openfda", source_url="https://example.test/1", source_text=SOURCE,
    )
    return a, b, interaction


def test_pending_carries_the_evidence_a_reviewer_needs(session):
    seed_pending(session)

    items = list_pending(session)

    assert len(items) == 1
    item = items[0]
    assert item.pair == "Calcium + Levothyroxine"
    assert item.severity == "moderate"
    assert item.evidence_grade == "B"
    assert item.spans == [SOURCE]
    assert item.sources == ["https://example.test/1"]


def test_published_items_are_not_in_the_queue(session):
    seed_pending(session, severity=Severity.MINOR)

    assert list_pending(session) == []


def test_approve_makes_an_interaction_visible_to_analysis(session):
    a, b, interaction = seed_pending(session)
    assert check_pairwise(session, [a.id, b.id]) == []

    approve(session, interaction.id)

    findings = check_pairwise(session, [a.id, b.id])
    assert len(findings) == 1
    assert list_pending(session) == []


def test_reject_keeps_it_hidden(session):
    a, b, interaction = seed_pending(session)

    reject(session, interaction.id)

    assert check_pairwise(session, [a.id, b.id]) == []
    row = session.scalars(select(Interaction)).one()
    assert row.status is InteractionStatus.REJECTED


def test_unknown_id_returns_none(session):
    assert approve(session, 9999) is None
    assert reject(session, 9999) is None


def test_decision_records_who_when_and_why(session):
    _, _, interaction = seed_pending(session)

    approve(session, interaction.id, reviewer="alice", note="label is explicit")

    row = session.get(Interaction, interaction.id)
    assert row.reviewed_by == "alice"
    assert row.reviewed_at is not None
    assert row.review_note == "label is explicit"


def test_reviewer_can_correct_severity_and_the_original_is_kept(session):
    _, _, interaction = seed_pending(session, severity=Severity.MAJOR)

    approve(
        session, interaction.id, reviewer="alice", note="absorption only",
        severity=Severity.MODERATE, evidence_grade=EvidenceGrade.A,
    )

    row = session.get(Interaction, interaction.id)
    assert row.severity is Severity.MODERATE
    assert row.evidence_grade is EvidenceGrade.A
    assert row.review_note == "absorption only; severity major -> moderate; evidence B -> A"


def test_reject_records_the_reviewer(session):
    _, _, interaction = seed_pending(session)

    reject(session, interaction.id, reviewer="alice", note="wrong pair")

    row = session.get(Interaction, interaction.id)
    assert (row.reviewed_by, row.review_note) == ("alice", "wrong pair")

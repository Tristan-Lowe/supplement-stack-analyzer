from sqlalchemy import select

from ssa.extract.gates import merge_triple
from ssa.models import (
    ConflictRecord,
    Entity,
    EntityKind,
    Evidence,
    EvidenceGrade,
    Interaction,
    InteractionStatus,
    Severity,
)
from ssa.registry import get_or_create_entity


def seed(session) -> tuple[Entity, Entity]:
    a = get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    b = get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()
    return a, b


def test_new_pair_is_created_pending_review(session):
    a, b = seed(session)

    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id,
        mechanism="Binding reduces absorption.",
        direction="decreases_absorption_of_b",
        severity=Severity.MODERATE, evidence_grade=EvidenceGrade.B,
        span="Calcium may bind levothyroxine.",
        source="openfda", source_url="https://example.test/1",
    )

    row = session.scalars(select(Interaction)).one()
    assert row.status is InteractionStatus.PENDING_REVIEW
    assert row.confidence == 0.6
    assert len(session.scalars(select(Evidence)).all()) == 1


def test_minor_severity_is_published_without_review(session):
    a, b = seed(session)

    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="Trivial effect.",
        direction="unclear", severity=Severity.MINOR, evidence_grade=EvidenceGrade.D,
        span="A minor effect was noted.", source="pubmed",
        source_url="https://example.test/2",
    )

    row = session.scalars(select(Interaction)).one()
    assert row.status is InteractionStatus.PUBLISHED


def test_agreeing_second_source_raises_confidence_and_adds_evidence(session):
    a, b = seed(session)
    common = dict(
        entity_a_id=a.id, entity_b_id=b.id,
        mechanism="Binding reduces absorption.",
        direction="decreases_absorption_of_b",
        severity=Severity.MODERATE, evidence_grade=EvidenceGrade.B,
    )
    merge_triple(session, **common, span="span one", source="openfda",
                 source_url="https://example.test/1")
    merge_triple(session, **common, span="span two", source="pubmed",
                 source_url="https://example.test/2")

    row = session.scalars(select(Interaction)).one()
    assert row.confidence > 0.6
    assert len(session.scalars(select(Evidence)).all()) == 2
    assert session.scalars(select(ConflictRecord)).all() == []


def test_disagreeing_severity_creates_conflict_and_keeps_higher(session):
    a, b = seed(session)
    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="decreases_absorption_of_b", severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B, span="span one", source="openfda",
        source_url="https://example.test/1",
    )
    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="decreases_absorption_of_b", severity=Severity.MAJOR,
        evidence_grade=EvidenceGrade.B, span="span two", source="pubmed",
        source_url="https://example.test/2",
    )

    row = session.scalars(select(Interaction)).one()
    assert row.severity is Severity.MAJOR
    conflict = session.scalars(select(ConflictRecord)).one()
    assert conflict.field == "severity"
    assert conflict.existing_value == "moderate"
    assert conflict.incoming_value == "major"


def test_pair_is_stored_in_a_stable_order(session):
    a, b = seed(session)

    merge_triple(
        session, entity_a_id=b.id, entity_b_id=a.id, mechanism="m",
        direction="unclear", severity=Severity.MINOR, evidence_grade=EvidenceGrade.D,
        span="s", source="openfda", source_url="https://example.test/1",
    )
    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="unclear", severity=Severity.MINOR, evidence_grade=EvidenceGrade.D,
        span="s2", source="pubmed", source_url="https://example.test/2",
    )

    rows = list(session.scalars(select(Interaction)).all())
    assert len(rows) == 1
    assert rows[0].entity_a_id < rows[0].entity_b_id

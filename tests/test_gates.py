import pytest
from sqlalchemy import select

from ssa.extract.gates import InvalidDirectionError, UnverifiedSpanError, merge_triple
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

SOURCE = (
    "Calcium carbonate may bind levothyroxine. A minor effect was noted. "
    "span one span two s s2"
)


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
        span="Calcium carbonate may bind levothyroxine.",
        source="openfda", source_url="https://example.test/1", source_text=SOURCE,
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
        source_url="https://example.test/2", source_text=SOURCE,
    )

    assert session.scalars(select(Interaction)).one().status is InteractionStatus.PUBLISHED


def test_agreeing_second_source_raises_confidence_and_adds_evidence(session):
    a, b = seed(session)
    common = dict(
        entity_a_id=a.id, entity_b_id=b.id,
        mechanism="Binding reduces absorption.",
        direction="decreases_absorption_of_b",
        severity=Severity.MODERATE, evidence_grade=EvidenceGrade.B,
        source_text=SOURCE,
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
    common = dict(
        entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="decreases_absorption_of_b", evidence_grade=EvidenceGrade.B,
        source_text=SOURCE,
    )
    merge_triple(session, **common, severity=Severity.MODERATE, span="span one",
                 source="openfda", source_url="https://example.test/1")
    merge_triple(session, **common, severity=Severity.MAJOR, span="span two",
                 source="pubmed", source_url="https://example.test/2")

    row = session.scalars(select(Interaction)).one()
    assert row.severity is Severity.MAJOR
    conflict = session.scalars(select(ConflictRecord)).one()
    assert conflict.field == "severity"
    assert conflict.existing_value == "moderate"
    assert conflict.incoming_value == "major"


def test_pair_is_stored_in_a_stable_order(session):
    a, b = seed(session)
    common = dict(
        mechanism="m", direction="unclear", severity=Severity.MINOR,
        evidence_grade=EvidenceGrade.D, source_text=SOURCE,
    )

    merge_triple(session, entity_a_id=b.id, entity_b_id=a.id, span="s",
                 source="openfda", source_url="https://example.test/1", **common)
    merge_triple(session, entity_a_id=a.id, entity_b_id=b.id, span="s2",
                 source="pubmed", source_url="https://example.test/2", **common)

    rows = list(session.scalars(select(Interaction)).all())
    assert len(rows) == 1
    assert rows[0].entity_a_id < rows[0].entity_b_id


# --- The system's governing invariant, enforced at the gate ---


def test_unverified_span_is_refused(session):
    """"No span, no triple" must not depend on the caller remembering to check."""
    a, b = seed(session)

    with pytest.raises(UnverifiedSpanError):
        merge_triple(
            session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
            direction="unclear", severity=Severity.MINOR, evidence_grade=EvidenceGrade.D,
            span="Calcium triples thyroid hormone levels.",
            source="openfda", source_url="https://example.test/1", source_text=SOURCE,
        )

    assert session.scalars(select(Interaction)).all() == []
    assert session.scalars(select(Evidence)).all() == []


def test_typographic_punctuation_still_verifies(session):
    """Curly apostrophes in FDA text must not manufacture quarantine noise."""
    a, b = seed(session)
    source = "St. John’s Wort induces CYP3A4 — reducing statin exposure."

    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="CYP3A4 induction.",
        direction="decreases_effect_of_b", severity=Severity.MAJOR,
        evidence_grade=EvidenceGrade.A,
        span="St. John's Wort induces CYP3A4 - reducing statin exposure.",
        source="pubmed", source_url="https://example.test/9", source_text=source,
    )

    assert session.scalars(select(Interaction)).one() is not None


# --- Confidence must measure corroboration, not repetition ---


def test_reingesting_the_same_source_does_not_inflate_confidence(session):
    a, b = seed(session)
    common = dict(
        entity_a_id=a.id, entity_b_id=b.id, mechanism="Binding reduces absorption.",
        direction="decreases_absorption_of_b", severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B, span="span one", source="openfda",
        source_url="https://example.test/1", source_text=SOURCE,
    )
    merge_triple(session, **common)
    merge_triple(session, **common)
    merge_triple(session, **common)

    row = session.scalars(select(Interaction)).one()
    assert row.confidence == 0.6
    assert len(session.scalars(select(Evidence)).all()) == 1


# --- A human review decision is not silently overridden ---


def test_rejected_interaction_is_not_resurrected(session):
    a, b = seed(session)
    interaction = merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="unclear", severity=Severity.MINOR, evidence_grade=EvidenceGrade.D,
        span="span one", source="openfda", source_url="https://example.test/1",
        source_text=SOURCE,
    )
    interaction.status = InteractionStatus.REJECTED
    session.commit()

    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="unclear", severity=Severity.MAJOR, evidence_grade=EvidenceGrade.D,
        span="span two", source="pubmed", source_url="https://example.test/2",
        source_text=SOURCE,
    )

    row = session.scalars(select(Interaction)).one()
    assert row.status is InteractionStatus.REJECTED
    assert row.severity is Severity.MAJOR  # evidence still accrues for later review


def test_evidence_grade_disagreement_is_recorded(session):
    a, b = seed(session)
    common = dict(
        entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="unclear", severity=Severity.MINOR, source_text=SOURCE,
    )
    merge_triple(session, **common, evidence_grade=EvidenceGrade.A, span="span one",
                 source="openfda", source_url="https://example.test/1")
    merge_triple(session, **common, evidence_grade=EvidenceGrade.D, span="span two",
                 source="pubmed", source_url="https://example.test/2")

    conflict = session.scalars(select(ConflictRecord)).one()
    assert conflict.field == "evidence_grade"
    assert conflict.existing_value == "A"
    assert conflict.incoming_value == "D"


def test_invalid_direction_is_refused(session):
    """The Direction Literal constrains the LLM; the gate must constrain every caller."""
    a, b = seed(session)

    with pytest.raises(InvalidDirectionError):
        merge_triple(
            session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
            direction="makes_it_weird", severity=Severity.MINOR,
            evidence_grade=EvidenceGrade.D, span="span one", source="openfda",
            source_url="https://example.test/1", source_text=SOURCE,
        )

    assert session.scalars(select(Interaction)).all() == []


def test_same_wording_under_different_urls_is_not_corroboration(session):
    """Generic labels replicate identical FDA wording across manufacturers.

    Five manufacturers carrying one sentence is one source, not five. Counting
    them separately would walk confidence 0.6 -> 0.99 on a single observation,
    in the number used to rank findings.
    """
    a, b = seed(session)
    common = dict(
        entity_a_id=a.id, entity_b_id=b.id, mechanism="Binding reduces absorption.",
        direction="decreases_absorption_of_b", severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B, span="Calcium carbonate may bind levothyroxine.",
        source="openfda", source_text=SOURCE,
    )
    for label_id in range(5):
        merge_triple(session, **common, source_url=f"https://example.test/label/{label_id}")

    row = session.scalars(select(Interaction)).one()
    assert row.confidence == 0.6
    assert len(session.scalars(select(Evidence)).all()) == 1


def test_genuinely_different_wording_still_corroborates(session):
    """The content check must not suppress real second sources."""
    a, b = seed(session)
    common = dict(
        entity_a_id=a.id, entity_b_id=b.id, mechanism="Binding reduces absorption.",
        direction="decreases_absorption_of_b", severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B, source="openfda", source_text=SOURCE,
    )
    merge_triple(session, **common, span="Calcium carbonate may bind levothyroxine.",
                 source_url="https://example.test/1")
    merge_triple(session, **common, span="A minor effect was noted.",
                 source_url="https://example.test/2")

    row = session.scalars(select(Interaction)).one()
    assert row.confidence > 0.6
    assert len(session.scalars(select(Evidence)).all()) == 2


def test_approved_interaction_is_not_silently_unpublished(session):
    """A later, more severe source must not withdraw a reviewer's approval.

    Observed in production: an approved Calcium + Levothyroxine interaction was
    reset to PENDING_REVIEW by a later section reporting MAJOR, vanishing from
    users with no notice.
    """
    a, b = seed(session)
    interaction = merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="unclear", severity=Severity.MODERATE, evidence_grade=EvidenceGrade.B,
        span="span one", source="openfda", source_url="https://example.test/1",
        source_text=SOURCE,
    )
    interaction.status = InteractionStatus.PUBLISHED
    session.commit()

    merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism="m",
        direction="unclear", severity=Severity.MAJOR, evidence_grade=EvidenceGrade.B,
        span="span two", source="pubmed", source_url="https://example.test/2",
        source_text=SOURCE,
    )

    row = session.scalars(select(Interaction)).one()
    assert row.status is InteractionStatus.PUBLISHED
    assert row.severity is Severity.MAJOR          # escalation still recorded
    conflicts = session.scalars(select(ConflictRecord)).all()
    assert any(c.field == "severity" for c in conflicts)  # reviewer can see it


def test_affected_entity_survives_pair_reordering(session):
    """The model's "b" must stay the affected compound after id-ordering the pair."""
    from ssa.models import EntityKind, EvidenceGrade, Severity
    from ssa.registry import get_or_create_entity

    levo = get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    orlistat = get_or_create_entity(session, EntityKind.DRUG, "Orlistat")
    session.commit()
    assert levo.id < orlistat.id
    text = "Orlistat may decrease levothyroxine absorption."

    row = merge_triple(
        session, entity_a_id=orlistat.id, entity_b_id=levo.id,
        mechanism="m", direction="decreases_absorption_of_b",
        severity=Severity.MODERATE, evidence_grade=EvidenceGrade.C,
        span=text, source="t", source_url="https://t/1", source_text=text,
    )

    assert (row.entity_a_id, row.entity_b_id) == (levo.id, orlistat.id)
    assert row.affected_entity_id == levo.id


def test_same_wording_about_opposite_compounds_is_a_conflict(session):
    from ssa.models import ConflictRecord, EntityKind, EvidenceGrade, Severity
    from ssa.registry import get_or_create_entity

    a = get_or_create_entity(session, EntityKind.DRUG, "Alpha")
    b = get_or_create_entity(session, EntityKind.DRUG, "Beta")
    session.commit()
    text = "Alpha and Beta interact."
    common = dict(
        mechanism="m", direction="decreases_effect_of_b", severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.C, span=text, source="t", source_text=text,
    )

    merge_triple(session, entity_a_id=a.id, entity_b_id=b.id, source_url="https://t/1", **common)
    merge_triple(session, entity_a_id=b.id, entity_b_id=a.id, source_url="https://t/2", **common)

    conflicts = session.query(ConflictRecord).filter_by(field="direction").all()
    assert len(conflicts) == 1

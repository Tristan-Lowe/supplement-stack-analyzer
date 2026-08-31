from unittest.mock import MagicMock, patch

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ssa.extract.schema import CandidateTriple, ExtractionResult
from ssa.models import EntityKind, EvidenceGrade, Interaction, QuarantinedTriple, Severity
from ssa.pipeline import ingest_section
from ssa.registry import get_or_create_entity

SOURCE = "Calcium carbonate may bind levothyroxine and reduce its absorption."


def make_result(span: str) -> ExtractionResult:
    return ExtractionResult(
        triples=[
            CandidateTriple(
                compound_a="Calcium",
                compound_b="Levothyroxine",
                mechanism="Binding reduces absorption.",
                direction="decreases_absorption_of_b",
                severity=Severity.MODERATE,
                evidence_grade=EvidenceGrade.B,
                span=span,
            )
        ]
    )


def test_verified_triple_is_stored(session):
    get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()

    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=make_result(SOURCE))

    stats = ingest_section(lambda: session, client, SOURCE, "openfda", "https://example.test/1")

    assert stats["stored"] == 1
    assert stats["quarantined"] == 0
    assert len(session.scalars(select(Interaction)).all()) == 1


def test_fabricated_span_is_quarantined_not_stored(session):
    get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()

    client = MagicMock()
    client.messages.parse.return_value = MagicMock(
        parsed_output=make_result("Calcium triples thyroid hormone levels.")
    )

    stats = ingest_section(lambda: session, client, SOURCE, "openfda", "https://example.test/1")

    assert stats["stored"] == 0
    assert stats["quarantined"] == 1
    assert session.scalars(select(Interaction)).all() == []
    assert session.scalars(select(QuarantinedTriple)).one().reason == "span_not_found"


def test_unresolvable_compound_is_quarantined(session):
    get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    session.commit()

    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=make_result(SOURCE))

    stats = ingest_section(
        lambda: session, client, SOURCE, "openfda", "https://example.test/1",
        allow_bootstrap=False,
    )

    assert stats["stored"] == 0
    assert stats["quarantined"] == 1
    assert session.scalars(select(QuarantinedTriple)).one().reason == "unresolved_compound"


def test_one_failing_triple_does_not_discard_the_run(session):
    """A poisoned Session used to lose the rest of an extraction already paid for."""
    get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()

    good = CandidateTriple(
        compound_a="Calcium", compound_b="Levothyroxine",
        mechanism="Binding reduces absorption.", direction="decreases_absorption_of_b",
        severity=Severity.MODERATE, evidence_grade=EvidenceGrade.B, span=SOURCE,
    )
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(
        parsed_output=ExtractionResult(triples=[good])
    )

    with patch("ssa.pipeline.merge_triple", side_effect=SQLAlchemyError("connection lost")):
        stats = ingest_section(
            lambda: session, client, SOURCE, "openfda", "https://example.test/1",
            allow_bootstrap=False,
        )

    assert stats["stored"] == 0
    assert stats["quarantined"] == 1
    assert session.scalars(select(QuarantinedTriple)).one().reason == "database_error"


def test_no_database_session_is_held_during_extraction(session):
    """The structural fix for Neon dropping connections mid-run.

    Extraction takes minutes. A session opened before it holds an idle connection
    with an open transaction for that whole time, which is exactly what serverless
    Postgres reclaims — and pool_pre_ping cannot help, because it validates a
    connection at checkout, not one already being held.

    So the ordering is the fix, and this test pins it: the session factory must not
    be called until the model call has returned.
    """
    get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()

    factory_called_during_extraction = False
    extraction_done = False

    def parse(*args, **kwargs):
        nonlocal extraction_done
        extraction_done = True
        return MagicMock(parsed_output=ExtractionResult(triples=[]))

    def factory():
        nonlocal factory_called_during_extraction
        if not extraction_done:
            factory_called_during_extraction = True
        return session

    client = MagicMock()
    client.messages.parse.side_effect = parse

    ingest_section(factory, client, SOURCE, "openfda", "https://example.test/1")

    assert not factory_called_during_extraction

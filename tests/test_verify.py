from sqlalchemy import select

from ssa.extract.schema import CandidateTriple
from ssa.extract.verify import quarantine, verify_span
from ssa.models import EvidenceGrade, QuarantinedTriple, Severity

SOURCE = (
    "Calcium carbonate and magnesium may bind levothyroxine and reduce its "
    "absorption. Separate administration by 4 hours."
)


def make_triple(span: str) -> CandidateTriple:
    return CandidateTriple(
        compound_a="calcium carbonate",
        compound_b="levothyroxine",
        mechanism="Binding in the gut reduces absorption.",
        direction="decreases_absorption_of_b",
        severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B,
        span=span,
    )


def test_exact_span_verifies():
    assert verify_span(make_triple("Separate administration by 4 hours."), SOURCE) is True


def test_span_with_different_whitespace_verifies():
    assert verify_span(make_triple("Separate  administration by\n4 hours."), SOURCE) is True


def test_fabricated_span_fails():
    assert verify_span(make_triple("Calcium triples thyroid hormone levels."), SOURCE) is False


def test_paraphrased_span_fails():
    assert verify_span(make_triple("Take them four hours apart."), SOURCE) is False


def test_quarantine_records_the_triple(session):
    triple = make_triple("Calcium triples thyroid hormone levels.")

    quarantine(session, triple, reason="span_not_found", detail="chunk 3 of openfda label abc")

    row = session.scalars(select(QuarantinedTriple)).one()
    assert row.reason == "span_not_found"
    assert row.payload["compound_a"] == "calcium carbonate"
    assert "chunk 3" in row.detail

import pytest
from pydantic import ValidationError

from ssa.extract.schema import CandidateTriple, ExtractionResult
from ssa.models import EvidenceGrade, Severity


def test_valid_triple_parses():
    triple = CandidateTriple(
        compound_a="calcium carbonate",
        compound_b="levothyroxine",
        mechanism="Calcium binds levothyroxine in the gut and reduces absorption.",
        direction="decreases_effect_of_b",
        severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B,
        span="Calcium carbonate may bind levothyroxine and reduce its absorption.",
    )
    assert triple.compound_a == "calcium carbonate"
    assert triple.severity is Severity.MODERATE


def test_empty_span_is_rejected():
    with pytest.raises(ValidationError):
        CandidateTriple(
            compound_a="a", compound_b="b", mechanism="m",
            direction="decreases_effect_of_b", severity=Severity.MINOR,
            evidence_grade=EvidenceGrade.D, span="   ",
        )


def test_invalid_direction_is_rejected():
    with pytest.raises(ValidationError):
        CandidateTriple(
            compound_a="a", compound_b="b", mechanism="m",
            direction="makes_it_weird", severity=Severity.MINOR,
            evidence_grade=EvidenceGrade.D, span="some text",
        )


def test_self_pair_is_rejected():
    with pytest.raises(ValidationError):
        CandidateTriple(
            compound_a="magnesium", compound_b="Magnesium", mechanism="m",
            direction="decreases_effect_of_b", severity=Severity.MINOR,
            evidence_grade=EvidenceGrade.D, span="some text",
        )


def test_extraction_result_allows_empty_list():
    result = ExtractionResult(triples=[])
    assert result.triples == []

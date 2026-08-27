from unittest.mock import MagicMock

from ssa.extract.llm import build_prompt, extract_triples
from ssa.extract.schema import CandidateTriple, ExtractionResult
from ssa.models import EvidenceGrade, Severity


def test_build_prompt_includes_source_text():
    prompt = build_prompt("Calcium may bind levothyroxine.")
    assert "Calcium may bind levothyroxine." in prompt
    assert "verbatim" in prompt.lower()


def test_extract_triples_returns_parsed_output():
    triple = CandidateTriple(
        compound_a="calcium",
        compound_b="levothyroxine",
        mechanism="Binding in the gut reduces absorption.",
        direction="decreases_absorption_of_b",
        severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B,
        span="Calcium may bind levothyroxine.",
    )
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(
        parsed_output=ExtractionResult(triples=[triple])
    )

    result = extract_triples(client, "Calcium may bind levothyroxine.", model="claude-opus-5")

    assert result.triples == [triple]
    kwargs = client.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["output_format"] is ExtractionResult
    assert kwargs["thinking"] == {"type": "adaptive"}


def test_extract_triples_returns_empty_result_when_parse_returns_none():
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(parsed_output=None)

    result = extract_triples(client, "Nothing relevant here.", model="claude-opus-5")

    assert result.triples == []

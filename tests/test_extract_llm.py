from unittest.mock import MagicMock

from ssa.extract.llm import build_prompt, build_request_kwargs, extract_triples
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


# --- The request shape must match the model, or the API returns 400 ---


def test_haiku_45_gets_neither_thinking_nor_effort():
    """Haiku 4.5 predates adaptive thinking and output_config.effort and rejects both."""
    assert build_request_kwargs("claude-haiku-4-5", "low") == {}


def test_current_models_get_adaptive_thinking_and_effort():
    kwargs = build_request_kwargs("claude-sonnet-5", "low")
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "low"}


def test_effort_is_omitted_when_not_requested():
    kwargs = build_request_kwargs("claude-opus-5", None)
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert "output_config" not in kwargs


def test_extract_triples_sends_no_thinking_for_haiku():
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(
        parsed_output=ExtractionResult(triples=[])
    )

    extract_triples(client, "text", model="claude-haiku-4-5")

    kwargs = client.messages.parse.call_args.kwargs
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs
    assert kwargs["model"] == "claude-haiku-4-5"

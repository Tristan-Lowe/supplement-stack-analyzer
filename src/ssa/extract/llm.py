"""Claude extraction call. Runs offline in a batch pipeline, never in the request path.

This is the only place an LLM touches interaction data, and its output is treated
as a candidate claim — the span verifier and validation gates decide what is stored.
"""

from __future__ import annotations

import logging

import anthropic

from ssa.config import Settings
from ssa.extract.schema import ExtractionResult

logger = logging.getLogger(__name__)

MAX_TOKENS = 16000

# Not every model accepts the same request shape, and sending the wrong one is a
# 400, not a graceful degradation.
#   - adaptive thinking and output_config.effort arrived with the 4.6 generation.
#     Haiku 4.5 rejects both; it predates them.
#   - effort is the main cost dial where it exists, because thinking tokens are
#     billed as output and output is ~93% of extraction cost.
MODELS_WITH_ADAPTIVE_THINKING: frozenset[str] = frozenset(
    {
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-fable-5",
    }
)

SYSTEM_PROMPT = """You extract drug and dietary-supplement interaction claims from \
source documents into structured records.

Rules you must follow:

1. Extract only what the source text actually states. Never add interactions you \
know about from elsewhere.
2. Every triple must include a `span` that is a verbatim, character-for-character \
quote copied from the source text. It will be checked programmatically against the \
source, and any triple whose span does not appear literally in the source is discarded.
3. Keep spans short — one or two sentences containing the claim.
4. If the source text states no interaction, return an empty list. An empty result \
is a correct and expected answer.
5. Assign `severity` by clinical consequence and `evidence_grade` by strength of \
evidence. They are independent: a theoretical interaction can rest on strong \
mechanistic work, and a major interaction can rest only on case reports."""


def build_prompt(source_text: str) -> str:
    """Build the user turn for one source document chunk."""
    return (
        "Extract every interaction claim stated in the source text below.\n\n"
        "Remember: each `span` must be a verbatim quote copied exactly from this text.\n\n"
        "<source_text>\n"
        f"{source_text}\n"
        "</source_text>"
    )


def make_client(settings: Settings | None = None) -> anthropic.Anthropic:
    resolved = settings or Settings()
    return anthropic.Anthropic(api_key=resolved.anthropic_api_key)


def build_request_kwargs(model: str, effort: str | None) -> dict:
    """Assemble the model-specific half of the request.

    Extraction is a read-and-transcribe task, not a reasoning task, so low effort
    is a reasonable default where the model supports it — and since thinking
    tokens bill as output, and output dominates the cost, it is also the main
    cost dial.
    """
    if model not in MODELS_WITH_ADAPTIVE_THINKING:
        return {}

    kwargs: dict = {"thinking": {"type": "adaptive"}}
    if effort:
        kwargs["output_config"] = {"effort": effort}
    return kwargs


def extract_triples(
    client: anthropic.Anthropic,
    source_text: str,
    model: str = "claude-opus-5",
    effort: str | None = "low",
) -> ExtractionResult:
    """Extract candidate triples from one chunk of source text.

    Returns an empty ExtractionResult rather than raising when the model produces
    no parsed output, so a single bad chunk cannot halt a pipeline run.
    """
    response = client.messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(source_text)}],
        output_format=ExtractionResult,
        **build_request_kwargs(model, effort),
    )

    parsed = response.parsed_output
    if parsed is None:
        logger.warning(
            "Extraction returned no parsed output for a %d-char chunk", len(source_text)
        )
        return ExtractionResult(triples=[])
    return parsed

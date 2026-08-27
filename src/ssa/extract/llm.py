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


def extract_triples(
    client: anthropic.Anthropic,
    source_text: str,
    model: str = "claude-opus-5",
) -> ExtractionResult:
    """Extract candidate triples from one chunk of source text.

    Returns an empty ExtractionResult rather than raising when the model produces
    no parsed output, so a single bad chunk cannot halt a pipeline run.
    """
    response = client.messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": build_prompt(source_text)}],
        output_format=ExtractionResult,
    )

    parsed = response.parsed_output
    if parsed is None:
        logger.warning(
            "Extraction returned no parsed output for a %d-char chunk", len(source_text)
        )
        return ExtractionResult(triples=[])
    return parsed

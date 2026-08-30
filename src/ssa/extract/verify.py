"""Verbatim span verification. Cheap, and it catches fabrication immediately.

A triple whose span does not literally appear in the source document is never
stored — it goes to quarantine so pipeline quality stays measurable.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session

from ssa.extract.schema import CandidateTriple
from ssa.models import QuarantinedTriple

_WS = re.compile(r"\s+")

# Typographic characters that FDA and NIH source text uses and that a model
# routinely reproduces as its ASCII equivalent. Folding these is not leniency
# about content — the words must still match exactly.
_TYPOGRAPHIC = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    " ": " ", "…": "...",
}


def collapse_for_comparison(text: str) -> str:
    """Normalize text for span comparison.

    Collapses whitespace runs, applies Unicode NFKC, and folds typographic
    punctuation to ASCII. This forgives transcription of a curly apostrophe or an
    en-dash — not paraphrase. Without it, ordinary FDA label punctuation produces
    quarantine noise that would drown the real fabrication signal.
    """
    folded = unicodedata.normalize("NFKC", text)
    for fancy, plain in _TYPOGRAPHIC.items():
        folded = folded.replace(fancy, plain)
    return _WS.sub(" ", folded).strip()


def span_appears_in(span: str, source_text: str) -> bool:
    """Return True when `span` appears verbatim in `source_text`.

    The core check. Whitespace and typographic punctuation are normalized on both
    sides; nothing else is forgiven — paraphrase, substitution, and invention fail.
    """
    return collapse_for_comparison(span) in collapse_for_comparison(source_text)


def verify_span(triple: CandidateTriple, source_text: str) -> bool:
    """Return True when the triple's span appears verbatim in the source text."""
    return span_appears_in(triple.span, source_text)


def quarantine(
    session: Session,
    triple: CandidateTriple,
    reason: str,
    detail: str = "",
) -> QuarantinedTriple:
    """Record a rejected triple. Never drop one silently.

    This commits deliberately. A quarantine record that is lost to a later
    rollback would make pipeline quality unmeasurable and would violate the
    "never silently dropped" rule, which outranks transaction tidiness here.
    Callers should not rely on holding unrelated uncommitted work across a
    quarantine call.
    """
    record = QuarantinedTriple(
        payload=triple.model_dump(mode="json"),
        reason=reason,
        detail=detail,
    )
    session.add(record)
    session.commit()
    return record

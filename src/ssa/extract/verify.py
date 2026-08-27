"""Verbatim span verification. Cheap, and it catches fabrication immediately.

A triple whose span does not literally appear in the source document is never
stored — it goes to quarantine so pipeline quality stays measurable.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ssa.extract.schema import CandidateTriple
from ssa.models import QuarantinedTriple

_WS = re.compile(r"\s+")


def _collapse(text: str) -> str:
    """Collapse all whitespace runs to single spaces so line wrapping does not matter."""
    return _WS.sub(" ", text).strip()


def verify_span(triple: CandidateTriple, source_text: str) -> bool:
    """Return True when the triple's span appears verbatim in the source text.

    Whitespace is normalized on both sides — a model reflowing a quoted sentence
    across lines is not fabrication. Nothing else is forgiven: paraphrase,
    substitution, and invention all fail.
    """
    return _collapse(triple.span) in _collapse(source_text)


def quarantine(
    session: Session,
    triple: CandidateTriple,
    reason: str,
    detail: str = "",
) -> QuarantinedTriple:
    """Record a rejected triple. Never drop one silently."""
    record = QuarantinedTriple(
        payload=triple.model_dump(mode="json"),
        reason=reason,
        detail=detail,
    )
    session.add(record)
    session.commit()
    return record

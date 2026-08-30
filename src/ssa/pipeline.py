"""Ingestion pipeline: source text in, verified interaction edges out.

Order matters. Extraction produces candidates; span verification runs before
anything touches the registry; unresolved compounds are quarantined rather than
guessed. Nothing reaches the knowledge store without passing both gates.
"""

from __future__ import annotations

import hashlib
import logging

import anthropic
from sqlalchemy.orm import Session

from ssa.extract.gates import merge_triple
from ssa.extract.llm import extract_triples
from ssa.extract.verify import collapse_for_comparison, quarantine, verify_span
from ssa.resolver import Resolved, resolve

logger = logging.getLogger(__name__)


def content_key(text: str) -> str:
    """Stable fingerprint of a source section, ignoring whitespace differences.

    Generic drugs carry the same FDA-mandated interaction wording under every
    manufacturer's label id, so one drug can return five near-identical sections.
    Extracting each of them costs five times as much for one document's worth of
    information.
    """
    return hashlib.sha256(collapse_for_comparison(text).encode("utf-8")).hexdigest()


def ingest_section(
    session: Session,
    client: anthropic.Anthropic,
    source_text: str,
    source: str,
    source_url: str,
    model: str = "claude-opus-5",
    pipeline_run_id: int | None = None,
) -> dict[str, int]:
    """Extract, verify, resolve, and merge every triple from one source section.

    Returns counts of stored and quarantined triples so pipeline quality stays
    measurable across runs.
    """
    result = extract_triples(client, source_text, model=model)
    stats = {"extracted": len(result.triples), "stored": 0, "quarantined": 0}

    for triple in result.triples:
        if not verify_span(triple, source_text):
            quarantine(session, triple, reason="span_not_found", detail=source_url)
            stats["quarantined"] += 1
            continue

        resolution_a = resolve(session, triple.compound_a)
        resolution_b = resolve(session, triple.compound_b)
        if not isinstance(resolution_a, Resolved) or not isinstance(resolution_b, Resolved):
            quarantine(session, triple, reason="unresolved_compound", detail=source_url)
            stats["quarantined"] += 1
            continue

        merge_triple(
            session,
            entity_a_id=resolution_a.entity_id,
            entity_b_id=resolution_b.entity_id,
            mechanism=triple.mechanism,
            direction=triple.direction,
            severity=triple.severity,
            evidence_grade=triple.evidence_grade,
            span=triple.span,
            source=source,
            source_url=source_url,
            source_text=source_text,
            pipeline_run_id=pipeline_run_id,
        )
        stats["stored"] += 1

    logger.info(
        "Ingested %s: %d extracted, %d stored, %d quarantined",
        source_url,
        stats["extracted"],
        stats["stored"],
        stats["quarantined"],
    )
    return stats

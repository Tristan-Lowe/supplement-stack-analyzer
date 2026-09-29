"""Ingestion pipeline: source text in, verified interaction edges out.

Order matters. Extraction produces candidates; span verification runs before
anything touches the registry; unresolved compounds are quarantined rather than
guessed. Nothing reaches the knowledge store without passing both gates.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

import anthropic
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ssa.bootstrap import bootstrap_entity
from ssa.extract.gates import InvalidDirectionError, UnverifiedSpanError, merge_triple
from ssa.extract.llm import extract_triples
from ssa.extract.schema import CandidateTriple
from ssa.extract.verify import collapse_for_comparison, quarantine, verify_span
from ssa.models import QuarantinedTriple
from ssa.resolver import Resolved, build_alias_index, resolve

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
    session_factory: Callable[[], Session],
    client: anthropic.Anthropic,
    source_text: str,
    source: str,
    source_url: str,
    model: str = "claude-opus-5",
    effort: str | None = "low",
    pipeline_run_id: int | None = None,
    allow_bootstrap: bool = True,
) -> dict[str, int]:
    """Extract, verify, resolve, and merge every triple from one source section.

    Takes a session *factory*, not a session, and this is load-bearing rather than
    stylistic. Extraction takes minutes; a session opened before it would hold an
    idle connection with a transaction attached for that whole time, which is
    exactly what serverless Postgres reclaims. pool_pre_ping cannot help — it
    validates a connection at checkout, not one already being held. So the model
    call happens with no connection held, and the database session is opened
    afterwards for the fast write phase.

    Returns counts of stored and quarantined triples so pipeline quality stays
    measurable across runs.
    """
    # Slow phase: no database connection is held here.
    result = extract_triples(client, source_text, model=model, effort=effort)

    # Fast phase: open the session only now.
    session = session_factory()
    try:
        return _store_triples(
            session, result, source_text, source, source_url, pipeline_run_id, allow_bootstrap
        )
    finally:
        session.close()


def _store_triples(
    session: Session,
    result,
    source_text: str,
    source: str,
    source_url: str,
    pipeline_run_id: int | None,
    allow_bootstrap: bool,
) -> dict[str, int]:
    """Resolve, verify and merge an already-extracted result. Fast, DB-bound."""
    stats = {
        "extracted": len(result.triples),
        "stored": 0,
        "quarantined": 0,
        "bootstrapped": 0,
    }

    def _resolve_or_bootstrap(name: str):
        """Resolve a compound, falling back to RxNorm to create it if unknown.

        Without this the graph cannot bootstrap: a fresh database recognises
        nothing, so every triple quarantines — including ones naming the very
        drug whose label is being read.
        """
        resolution = resolve(session, name)
        if isinstance(resolution, Resolved) or not allow_bootstrap:
            return resolution
        if bootstrap_entity(session, name) is None:
            return resolution
        stats["bootstrapped"] += 1
        return resolve(session, name)

    for triple in result.triples:
        if not verify_span(triple, source_text):
            quarantine(session, triple, reason="span_not_found", detail=source_url)
            stats["quarantined"] += 1
            continue

        resolution_a = _resolve_or_bootstrap(triple.compound_a)
        resolution_b = _resolve_or_bootstrap(triple.compound_b)
        if not isinstance(resolution_a, Resolved) or not isinstance(resolution_b, Resolved):
            quarantine(session, triple, reason="unresolved_compound", detail=source_url)
            stats["quarantined"] += 1
            continue

        # One bad triple must not discard the rest of a paid-for extraction run.
        # A failed flush leaves the Session unusable, so every later query in the
        # run raises PendingRollbackError and the whole section is lost — the most
        # expensive possible way to fail. Roll back, record why, and carry on.
        try:
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
        except (UnverifiedSpanError, InvalidDirectionError) as exc:
            session.rollback()
            quarantine(session, triple, reason="rejected_by_gate", detail=f"{source_url}: {exc}")
            stats["quarantined"] += 1
            continue
        except SQLAlchemyError as exc:
            session.rollback()
            quarantine(
                session, triple, reason="database_error", detail=f"{source_url}: {exc}"[:2000]
            )
            stats["quarantined"] += 1
            logger.warning(
                "merge failed for %s + %s: %s",
                triple.compound_a,
                triple.compound_b,
                exc,
            )
            continue

        stats["stored"] += 1

    logger.info(
        "Ingested %s: %d extracted, %d stored, %d quarantined, %d bootstrapped",
        source_url,
        stats["extracted"],
        stats["stored"],
        stats["quarantined"],
        stats["bootstrapped"],
    )
    return stats


def replay_quarantine(session: Session) -> dict[str, int]:
    """Retry triples quarantined only because a compound did not resolve.

    Their spans were verified before quarantine, so nothing is re-extracted and
    nothing is paid for. The registry improves over time (curated seeds, brand
    aliases), and a claim should not stay lost because the registry was younger
    than the document.

    Offline by design: no RxNorm bootstrap. A replay binds only names the
    registry already recognises. Recovered rows go through merge_triple like any
    other claim, so moderate-or-above ones land in the review queue. Rows that
    still do not resolve stay quarantined.
    """
    stats = {"examined": 0, "recovered": 0, "still_unresolved": 0, "self_pairs": 0}
    rows = session.scalars(
        select(QuarantinedTriple).where(QuarantinedTriple.reason == "unresolved_compound")
    ).all()
    index = build_alias_index(session)

    for row in rows:
        stats["examined"] += 1
        triple = CandidateTriple.model_validate(row.payload)
        a = resolve(session, triple.compound_a, alias_index=index)
        b = resolve(session, triple.compound_b, alias_index=index)
        if not isinstance(a, Resolved) or not isinstance(b, Resolved):
            stats["still_unresolved"] += 1
            continue
        if a.entity_id == b.entity_id:
            stats["self_pairs"] += 1
            continue

        merge_triple(
            session,
            entity_a_id=a.entity_id,
            entity_b_id=b.entity_id,
            mechanism=triple.mechanism,
            direction=triple.direction,
            severity=triple.severity,
            evidence_grade=triple.evidence_grade,
            span=triple.span,
            source="openfda",
            source_url=row.detail,
            source_text=triple.span,  # verified against the label before quarantine
        )
        session.delete(row)
        session.commit()
        stats["recovered"] += 1

    return stats

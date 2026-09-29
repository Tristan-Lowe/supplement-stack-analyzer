"""The public checker's request path: snapshot load, request validation, JSON output.

The deployed site never connects to the production database. At build time
`export_snapshot` writes the *published* graph to a JSON file that ships inside
the deployment; at cold start `load_snapshot` rebuilds it in an in-memory SQLite
database. Three consequences, all deliberate:

- No database credential exists in the deployment, so none can leak.
- Nothing pending review, rejected, or quarantined can reach a user.
- The graph is read-only from the internet by construction.

Everything user-facing is plain data. The browser renders it with textContent,
and citation URLs are filtered to an allowlist of hosts here as well as there.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from ssa.analyze.engine import analyze_stack
from ssa.analyze.findings import FindingKind
from ssa.models import (
    Base,
    Entity,
    EntityAlias,
    EntityKind,
    Evidence,
    EvidenceGrade,
    Interaction,
    InteractionStatus,
    Severity,
    TimingRule,
    UpperLimit,
)

SNAPSHOT_VERSION = 1

# Request limits. A real stack is a few hundred characters; these are generous
# for people and tight for abuse.
MAX_BODY_BYTES = 8_192
MAX_TEXT_CHARS = 2_000
MAX_ITEMS = 40

# Only these hosts are ever rendered as links. Anything else is shown as text.
CITATION_HOSTS: frozenset[str] = frozenset({"api.fda.gov", "ods.od.nih.gov"})


# --- Snapshot -------------------------------------------------------------


def export_snapshot(session: Session) -> dict:
    """Serialise the published graph. Pending and rejected rows are excluded."""
    interactions = session.scalars(
        select(Interaction)
        .options(selectinload(Interaction.evidence))
        .where(Interaction.status == InteractionStatus.PUBLISHED)
        .order_by(Interaction.id)
    ).all()

    return {
        "version": SNAPSHOT_VERSION,
        "entities": [
            {"id": e.id, "kind": e.kind.name, "name": e.canonical_name}
            for e in session.scalars(select(Entity).order_by(Entity.id)).all()
        ],
        "aliases": [
            {"entity_id": a.entity_id, "alias": a.alias, "normalized": a.normalized_alias}
            for a in session.scalars(select(EntityAlias).order_by(EntityAlias.id)).all()
        ],
        "interactions": [
            {
                "a": i.entity_a_id,
                "b": i.entity_b_id,
                "mechanism": i.mechanism,
                "direction": i.direction,
                "affected": i.affected_entity_id,
                "severity": i.severity.name,
                "grade": i.evidence_grade.name,
                "confidence": i.confidence,
                "evidence": [
                    {"source": ev.source, "url": ev.source_url, "span": ev.span}
                    for ev in i.evidence
                ],
            }
            for i in interactions
        ],
        "upper_limits": [
            {
                "entity_id": u.entity_id,
                "amount": u.amount,
                "unit": u.unit,
                "population": u.population,
                "basis": u.basis,
                "url": u.source_url,
            }
            for u in session.scalars(select(UpperLimit)).all()
        ],
        "timing_rules": [
            {
                "a": t.entity_a_id,
                "b": t.entity_b_id,
                "hours": t.separation_hours,
                "note": t.note,
                "url": t.source_url,
            }
            for t in session.scalars(select(TimingRule)).all()
        ],
    }


def load_snapshot(path: str | Path) -> sessionmaker:
    """Rebuild a snapshot into in-memory SQLite. Returns a session factory."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"unsupported snapshot version {data.get('version')!r}")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    with factory() as session:
        session.add_all(
            Entity(id=e["id"], kind=EntityKind[e["kind"]], canonical_name=e["name"])
            for e in data["entities"]
        )
        session.flush()
        session.add_all(
            EntityAlias(
                entity_id=a["entity_id"],
                alias=a["alias"],
                normalized_alias=a["normalized"],
                source="snapshot",
            )
            for a in data["aliases"]
        )
        for row in data["interactions"]:
            interaction = Interaction(
                entity_a_id=row["a"],
                entity_b_id=row["b"],
                mechanism=row["mechanism"],
                direction=row["direction"],
                affected_entity_id=row["affected"],
                severity=Severity[row["severity"]],
                evidence_grade=EvidenceGrade[row["grade"]],
                confidence=row["confidence"],
                status=InteractionStatus.PUBLISHED,
            )
            interaction.evidence = [
                Evidence(source=ev["source"], source_url=ev["url"], span=ev["span"])
                for ev in row["evidence"]
            ]
            session.add(interaction)
        session.add_all(
            UpperLimit(
                entity_id=u["entity_id"],
                amount=u["amount"],
                unit=u["unit"],
                population=u["population"],
                basis=u["basis"],
                source_url=u["url"],
            )
            for u in data["upper_limits"]
        )
        session.add_all(
            TimingRule(
                entity_a_id=t["a"],
                entity_b_id=t["b"],
                separation_hours=t["hours"],
                note=t["note"],
                source_url=t["url"],
            )
            for t in data["timing_rules"]
        )
        session.commit()
    return factory


# --- Request handling -----------------------------------------------------


def safe_citation_url(url: str) -> str | None:
    """Return the URL only if it is https on an allowlisted host."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname not in CITATION_HOSTS:
        return None
    if parsed.username or parsed.password or parsed.port:
        return None
    return url


def _source_label(url: str) -> str:
    host = urlparse(url).hostname or ""
    if host == "api.fda.gov":
        return "FDA drug label"
    if host == "ods.od.nih.gov":
        return "NIH fact sheet"
    return "Source"


def serialize_report(report) -> dict:
    """Plain JSON for the browser. Every string is data, never markup."""
    findings = []
    for f in report.findings:
        if f.kind is FindingKind.UNRESOLVED and f.severity is Severity.THEORETICAL:
            continue  # the unidentified list is returned separately below
        citations = []
        seen: set[str] = set()
        for c in f.citations:
            url = safe_citation_url(c.source_url)
            key = url or c.span
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                {"label": _source_label(c.source_url), "url": url, "quote": c.span}
            )
        findings.append(
            {
                "kind": f.kind.value,
                "severity": f.severity.value,
                "title": f.title,
                "detail": f.detail,
                "citations": citations[:4],
            }
        )
    return {
        "summary": report.summary,
        "identified": report.resolved_count,
        "unidentified": report.unresolved,
        "findings": findings,
        "disclaimer": report.disclaimer,
    }


class RateLimiter:
    """Sliding-window limit per client, in memory.

    Keys are truncated hashes, so no address is held in plain form, and nothing is
    written anywhere. Per serverless instance only: it blunts a single noisy client,
    it is not a global quota.
    """

    def __init__(self, limit: int = 30, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, client: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        key = hashlib.sha256(client.encode("utf-8")).hexdigest()[:16]
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory under a spray of clients
            self._hits.clear()
        return True


def _error(status: int, message: str) -> tuple[int, dict]:
    return status, {"error": message}


def handle_analyze(
    session: Session,
    body: bytes,
    content_type: str | None,
    origin: str | None,
    host: str | None,
) -> tuple[int, dict]:
    """Validate one request and run the analysis. Returns (status, JSON body).

    Error messages name what to fix and never echo internals.
    """
    if origin is not None and host is not None and urlparse(origin).netloc != host:
        return _error(403, "Requests must come from this site.")
    if not content_type or content_type.split(";")[0].strip().lower() != "application/json":
        return _error(415, "Send the stack as JSON.")
    if len(body) > MAX_BODY_BYTES:
        return _error(413, "That stack is too long. Keep it under 2,000 characters.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "The request could not be read. Reload the page and try again.")
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        return _error(400, "The request could not be read. Reload the page and try again.")

    text = payload["text"].strip()
    if not text:
        return _error(422, "Add at least one supplement or medication.")
    if len(text) > MAX_TEXT_CHARS:
        return _error(413, "That stack is too long. Keep it under 2,000 characters.")
    items = [p for line in text.splitlines() for p in line.split(",") if p.strip()]
    if len(items) > MAX_ITEMS:
        return _error(413, f"Check up to {MAX_ITEMS} items at a time.")

    report = analyze_stack(session, text)
    return 200, serialize_report(report)

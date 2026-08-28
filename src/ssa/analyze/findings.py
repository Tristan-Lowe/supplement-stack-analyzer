"""The shared output type every analysis check produces, plus ranking."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from ssa.models import SEVERITY_RANK, Severity


class FindingKind(enum.StrEnum):
    INTERACTION = "interaction"
    REDUNDANCY = "redundancy"
    UPPER_LIMIT = "upper_limit"
    TIMING = "timing"
    UNRESOLVED = "unresolved"


class Tier(enum.StrEnum):
    """Provenance of a finding. Fallback-tier results are never blended with graph-tier."""

    GRAPH = "graph"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class Citation:
    source: str
    source_url: str
    span: str


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    severity: Severity
    title: str
    detail: str
    entity_ids: list[int]
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 1.0
    tier: Tier = Tier.GRAPH


def format_labels(labels: list[str]) -> str:
    """Render source labels for display, collapsing repeats.

    A user who enters the same product twice should see "Vitamin B6 x2", not
    "Vitamin B6, Vitamin B6" — the repeated form reads like a rendering bug and
    tells the reader nothing.
    """
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return ", ".join(name if n == 1 else f"{name} x{n}" for name, n in counts.items())


def rank_findings(findings: list[Finding]) -> list[Finding]:
    """Order findings by severity, then graph tier over fallback, then confidence.

    Tier outranks confidence deliberately: a verified graph finding should never sit
    below an unverified one just because the fallback tier reported a higher number.
    """
    return sorted(
        findings,
        key=lambda f: (
            SEVERITY_RANK[f.severity],
            0 if f.tier is Tier.FALLBACK else 1,
            f.confidence,
        ),
        reverse=True,
    )

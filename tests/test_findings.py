from ssa.analyze.findings import Finding, FindingKind, Tier, rank_findings
from ssa.models import Severity


def make(kind: FindingKind, severity: Severity, confidence: float, title: str) -> Finding:
    return Finding(
        kind=kind, severity=severity, title=title, detail="",
        entity_ids=[], citations=[], confidence=confidence, tier=Tier.GRAPH,
    )


def test_rank_orders_by_severity_then_confidence():
    findings = [
        make(FindingKind.INTERACTION, Severity.MINOR, 0.9, "minor"),
        make(FindingKind.INTERACTION, Severity.MAJOR, 0.5, "major-low-conf"),
        make(FindingKind.INTERACTION, Severity.MAJOR, 0.9, "major-high-conf"),
    ]

    ranked = rank_findings(findings)

    assert [f.title for f in ranked] == ["major-high-conf", "major-low-conf", "minor"]


def test_graph_tier_outranks_fallback_at_equal_severity():
    graph = make(FindingKind.INTERACTION, Severity.MODERATE, 0.7, "graph")
    fallback = Finding(
        kind=FindingKind.INTERACTION, severity=Severity.MODERATE, title="fallback",
        detail="", entity_ids=[], citations=[], confidence=0.9, tier=Tier.FALLBACK,
    )

    ranked = rank_findings([fallback, graph])

    assert [f.title for f in ranked] == ["graph", "fallback"]


def test_rank_of_empty_list_is_empty():
    assert rank_findings([]) == []

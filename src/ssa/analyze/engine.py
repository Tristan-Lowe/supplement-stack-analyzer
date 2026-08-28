"""Analysis orchestrator. Resolves a stack, runs all four checks, ranks the results.

Contains no LLM call and no network I/O. The only claim this module will ever make
about an absence of findings is "no known interactions among the compounds we could
identify" — never that a stack is safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ssa.analyze.findings import Finding, FindingKind, Tier, rank_findings
from ssa.analyze.limits import check_upper_limits
from ssa.analyze.pairwise import check_pairwise
from ssa.analyze.redundancy import ResolvedDose, check_redundancy
from ssa.analyze.timing import check_timing
from ssa.models import Severity
from ssa.resolver import Ambiguous, Resolved, Unknown, resolve
from ssa.stack import parse_stack_text

DISCLAIMER = (
    "This tool reports published information for education. It is not medical advice "
    "and does not replace a pharmacist or physician."
)


@dataclass
class AnalysisReport:
    findings: list[Finding]
    resolved_count: int
    unresolved: list[str] = field(default_factory=list)
    summary: str = ""
    disclaimer: str = DISCLAIMER


def _summarize(findings: list[Finding], resolved_count: int, unresolved: list[str]) -> str:
    """Build the headline sentence.

    The no-findings wording is load-bearing and deliberately not reassuring: it
    scopes the claim to the compounds that were actually identified.
    """
    if findings:
        plural = "s" if len(findings) != 1 else ""
        compounds = "s" if resolved_count != 1 else ""
        lead = (
            f"{len(findings)} finding{plural} across {resolved_count} "
            f"identified compound{compounds}."
        )
    else:
        compounds = "s" if resolved_count != 1 else ""
        lead = (
            f"No known interactions among the {resolved_count} "
            f"compound{compounds} we could identify."
        )

    if unresolved:
        items = "s" if len(unresolved) != 1 else ""
        lead += (
            f" {len(unresolved)} item{items} could not be identified and were not checked."
        )
    return lead


def analyze_stack(session: Session, stack_text: str) -> AnalysisReport:
    """Run the full deterministic analysis over a stack given as text."""
    items = parse_stack_text(stack_text)

    doses: list[ResolvedDose] = []
    entity_ids: list[int] = []
    unresolved: list[str] = []

    for item in items:
        result = resolve(session, item.raw)
        if isinstance(result, Resolved):
            entity_ids.append(result.entity_id)
            doses.append(
                ResolvedDose(
                    entity_id=result.entity_id,
                    amount=item.amount,
                    unit=item.unit,
                    source_label=item.raw,
                )
            )
        elif isinstance(result, Ambiguous | Unknown):
            unresolved.append(item.raw)

    findings: list[Finding] = []
    findings.extend(check_pairwise(session, entity_ids))
    findings.extend(check_timing(session, entity_ids))
    findings.extend(check_redundancy(session, doses))
    findings.extend(check_upper_limits(session, doses))

    if unresolved:
        findings.append(
            Finding(
                kind=FindingKind.UNRESOLVED,
                severity=Severity.THEORETICAL,
                title="Some items could not be identified",
                detail=(
                    "These were not checked because they are not in our database: "
                    + ", ".join(unresolved)
                    + "."
                ),
                entity_ids=[],
                citations=[],
                confidence=1.0,
                tier=Tier.GRAPH,
            )
        )

    ranked = rank_findings(findings)
    resolved_count = len(set(entity_ids))

    return AnalysisReport(
        findings=ranked,
        resolved_count=resolved_count,
        unresolved=unresolved,
        summary=_summarize(
            [f for f in ranked if f.kind is not FindingKind.UNRESOLVED],
            resolved_count,
            unresolved,
        ),
    )

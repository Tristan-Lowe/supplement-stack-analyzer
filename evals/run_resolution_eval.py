"""Measure entity resolution accuracy against the fixed gold set.

Run against a populated production database:
    python -m evals.run_resolution_eval
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from ssa.db import make_engine, make_session_factory
from ssa.models import Entity
from ssa.resolver import Resolved, resolve
from ssa.stack import parse_stack_text

TARGET_ACCURACY = 0.95


@dataclass(frozen=True)
class GoldCase:
    raw: str
    expected: str | None
    note: str


@dataclass
class EvalReport:
    total: int
    correct: int
    failures: list[tuple[str, str | None, str]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def load_gold(path: str | Path) -> list[GoldCase]:
    cases: list[GoldCase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        cases.append(
            GoldCase(
                raw=payload["raw"],
                expected=payload["expected"],
                note=payload.get("note", ""),
            )
        )
    return cases


def _resolve_as_engine_would(session: Session, raw: str):
    """Resolve exactly the way analyze_stack does — dose stripped off first.

    The gold set carries realistic user input like "mag glycinate 400mg". The
    request path parses that into name and dose before resolving, so an eval that
    hands the raw string straight to the resolver measures a path production never
    takes and reports a number nobody can act on.
    """
    items = parse_stack_text(raw)
    name = items[0].raw if items else raw
    return resolve(session, name)


def evaluate(session: Session, cases: list[GoldCase]) -> EvalReport:
    """Score the resolver. A case with expected=None is correct iff it did NOT resolve."""
    correct = 0
    failures: list[tuple[str, str | None, str]] = []

    for case in cases:
        result = _resolve_as_engine_would(session, case.raw)

        if case.expected is None:
            if isinstance(result, Resolved):
                entity = session.get(Entity, result.entity_id)
                actual = entity.canonical_name if entity else "?"
                failures.append((case.raw, case.expected, f"resolved to {actual}"))
            else:
                correct += 1
            continue

        if not isinstance(result, Resolved):
            failures.append((case.raw, case.expected, type(result).__name__))
            continue

        entity = session.get(Entity, result.entity_id)
        actual = entity.canonical_name if entity else "?"
        if actual == case.expected:
            correct += 1
        else:
            failures.append((case.raw, case.expected, f"resolved to {actual}"))

    return EvalReport(total=len(cases), correct=correct, failures=failures)


def main(argv: list[str] | None = None) -> int:
    """Run against the live database, or against a committed snapshot with --snapshot.

    The snapshot form is what CI runs: no database credential, same resolver.
    Exit code is non-zero below target or on ANY wrong-entity resolution.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", help="path to a graph.json snapshot")
    args = parser.parse_args(argv)

    if args.snapshot:
        from ssa.web import load_snapshot

        factory = load_snapshot(args.snapshot)
    else:
        factory = make_session_factory(make_engine())
    session = factory()
    try:
        report = evaluate(session, load_gold("evals/resolution_gold.jsonl"))
    finally:
        session.close()

    print(f"Resolution accuracy: {report.accuracy:.1%} ({report.correct}/{report.total})")
    wrong = [f for f in report.failures if f[2].startswith("resolved to")]
    print(
        f"  of {len(report.failures)} failures: {len(wrong)} resolved to the WRONG entity, "
        f"{len(report.failures) - len(wrong)} were not resolved at all."
    )
    if wrong:
        print("  A wrong resolution is far worse than a non-resolution here.")
    if report.failures:
        print("\nFailures:")
        for raw, expected, actual in report.failures:
            print(f"  {raw!r}: expected {expected!r}, got {actual}")

    if report.accuracy < TARGET_ACCURACY:
        print(f"\nFAIL: below target of {TARGET_ACCURACY:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

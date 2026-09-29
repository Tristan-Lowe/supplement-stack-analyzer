"""Interaction recall against the independent gold set.

Each gold pair is run through analyze_stack exactly as a user's two-line stack
would be. A pair counts as found when an interaction finding for it comes back.
Misses are split by cause, because the fixes differ:

- **unrecognised**: a name did not resolve (registry coverage)
- **no edge**: both resolved, but the graph holds no published interaction
  (source coverage — the drug's label has not been read, or does not say it)

    python -m evals.run_interaction_eval [--snapshot evals/snapshot/graph.json]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from ssa.analyze.engine import analyze_stack
from ssa.analyze.findings import FindingKind

GOLD = Path("evals/interaction_gold.jsonl")


@dataclass
class RecallReport:
    total: int = 0
    found: int = 0
    unrecognised: list[str] = field(default_factory=list)
    no_edge: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.found / self.total if self.total else 0.0


def load_gold(path: Path = GOLD) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def evaluate(session: Session, rows: list[dict]) -> RecallReport:
    report = RecallReport()
    for row in rows:
        if not row.get("significant", True):
            continue
        report.total += 1
        label = f"{row['a']} + {row['b']}"
        result = analyze_stack(session, f"{row['a']}\n{row['b']}")
        if any(f.kind is FindingKind.INTERACTION for f in result.findings):
            report.found += 1
        elif result.unresolved:
            report.unrecognised.append(f"{label} (not recognised: {', '.join(result.unresolved)})")
        else:
            report.no_edge.append(label)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot")
    parser.add_argument(
        "--min-recall", type=float, default=None,
        help="exit non-zero below this recall (the regression gate)",
    )
    args = parser.parse_args(argv)
    if args.snapshot:
        from ssa.web import load_snapshot

        factory = load_snapshot(args.snapshot)
    else:
        from ssa.db import make_engine, make_session_factory

        factory = make_session_factory(make_engine())

    with factory() as session:
        report = evaluate(session, load_gold())

    print(f"Interaction recall: {report.recall:.1%} ({report.found}/{report.total})")
    print(f"  missed, name not recognised: {len(report.unrecognised)}")
    print(f"  missed, no interaction in the graph: {len(report.no_edge)}")
    for line in report.unrecognised:
        print(f"    unrecognised  {line}")
    for line in report.no_edge:
        print(f"    no edge       {line}")
    if args.min_recall is not None and report.recall + 1e-9 < args.min_recall:
        print()
        print(f"FAIL: recall {report.recall:.1%} is below the baseline {args.min_recall:.1%}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

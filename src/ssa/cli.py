"""Command-line entry points for seeding, ingesting, and analyzing."""

from __future__ import annotations

import argparse

from ssa.analyze.engine import analyze_stack
from ssa.config import Settings
from ssa.connectors.ods import load_upper_limits
from ssa.connectors.openfda import fetch_interaction_sections
from ssa.db import make_engine, make_session_factory
from ssa.extract.llm import make_client
from ssa.models import PipelineRun, utcnow
from ssa.pipeline import ingest_section


def _session():
    return make_session_factory(make_engine())()


def cmd_seed(args: argparse.Namespace) -> int:
    session = _session()
    try:
        created = load_upper_limits(session, args.csv)
        print(f"Loaded {created} new upper limits.")
    finally:
        session.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest one drug's label sections under a tracked pipeline run.

    Every interaction edge is stamped with the run that produced it, which is what
    makes releases diffable.
    """
    settings = Settings()
    session = _session()
    client = make_client(settings)
    totals = {"extracted": 0, "stored": 0, "quarantined": 0}

    run = PipelineRun(source="openfda", stats={})
    session.add(run)
    session.commit()

    try:
        sections = fetch_interaction_sections(args.drug)
        if not sections:
            print(f"No label sections retrieved for {args.drug!r}.")
            run.finished_at = utcnow()
            run.stats = {"drug": args.drug, "sections": 0, **totals}
            session.commit()
            return 1

        for section in sections:
            stats = ingest_section(
                session,
                client,
                section.text,
                source="openfda",
                source_url=section.source_url,
                model=settings.extraction_model,
                pipeline_run_id=run.id,
            )
            for key in totals:
                totals[key] += stats[key]

        run.finished_at = utcnow()
        run.stats = {"drug": args.drug, "sections": len(sections), **totals}
        session.commit()
        run_id = run.id
    finally:
        session.close()

    print(
        f"{args.drug} (run {run_id}): {totals['extracted']} extracted, "
        f"{totals['stored']} stored, {totals['quarantined']} quarantined."
    )
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    session = _session()
    try:
        report = analyze_stack(session, args.stack)
    finally:
        session.close()

    print(report.summary)
    print()
    for finding in report.findings:
        print(f"[{finding.severity.value.upper()}] {finding.title}")
        print(f"  {finding.detail}")
        for citation in finding.citations:
            print(f"  source: {citation.source_url}")
        print()
    print(report.disclaimer)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ssa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed = subparsers.add_parser("seed", help="Load upper intake limits from CSV")
    seed.add_argument("--csv", default="data/upper_limits.csv")
    seed.set_defaults(func=cmd_seed)

    ingest = subparsers.add_parser("ingest", help="Ingest openFDA label sections for a drug")
    ingest.add_argument("drug")
    ingest.set_defaults(func=cmd_ingest)

    analyze = subparsers.add_parser("analyze", help="Analyze a stack given as text")
    analyze.add_argument("stack")
    analyze.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Ingest a list of drugs, then enrich brand names and replay quarantine.

    python scripts/ingest_batch.py data/ingest_targets.csv

Resumable: a drug with a finished pipeline run that extracted at least one section
is skipped, so a crash part-way never pays for the same label twice. Each drug is
its own pipeline run, and one drug failing does not stop the rest.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anthropic  # noqa: E402

from ssa.cli import _session, cmd_enrich, cmd_ingest, cmd_replay  # noqa: E402
from ssa.models import PipelineRun  # noqa: E402


def already_ingested() -> set[str]:
    session = _session()
    try:
        done = set()
        for run in session.scalars(select(PipelineRun)).all():
            stats = run.stats if isinstance(run.stats, dict) else {}
            if run.finished_at and stats.get("drug") and stats.get("sections_extracted", 0) > 0:
                done.add(stats["drug"].lower())
        return done
    finally:
        session.close()


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else ROOT / "data" / "ingest_targets.csv"
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    done = already_ingested()
    failures: list[str] = []

    for row in rows:
        drug = row["drug"].strip()
        if drug.lower() in done:
            print(f"skip  {drug} (already ingested)", flush=True)
            continue
        started = time.monotonic()
        print(f"start {drug} [{row.get('group', '')}]", flush=True)
        try:
            code = cmd_ingest(argparse.Namespace(drug=drug))
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            # A bad key fails every drug identically; stop instead of marching on.
            print(f"  fatal: {type(exc).__name__}. Check ANTHROPIC_API_KEY in .env.", flush=True)
            return 2
        except Exception as exc:  # keep going; report at the end
            code = 1
            print(f"  error: {type(exc).__name__}: {exc}", flush=True)
        if code != 0:
            failures.append(drug)
        print(f"done  {drug} in {time.monotonic() - started:.0f}s (exit {code})", flush=True)

    print("\n== enrich ==", flush=True)
    cmd_enrich(argparse.Namespace(all=False))
    print("\n== replay ==", flush=True)
    cmd_replay(argparse.Namespace())
    print(f"\nFailures: {failures or 'none'}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Build the public checker for deployment.

    python scripts/build_site.py      # then: cd site && vercel deploy --prod

1. Exports the *published* graph from DATABASE_URL to site/api/_lib/graph.json.
2. Copies the request-path modules of `ssa` into site/api/_lib/ssa. The deployed
   function needs only these; nothing that talks to Anthropic, RxNorm, or Postgres
   is shipped.
3. Renders site/template/index.html into site/public/index.html, filling the
   coverage numbers from the same snapshot, so the page never states a number the
   data does not support.

Generated paths are git-ignored. Re-run after every review batch.
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
LIB = SITE / "api" / "_lib"
sys.path.insert(0, str(ROOT / "src"))

from ssa.db import make_engine, make_session_factory  # noqa: E402
from ssa.web import export_snapshot  # noqa: E402

# The request path, and nothing else.
MODULES = [
    "__init__.py",
    "models.py",
    "normalize.py",
    "registry.py",
    "resolver.py",
    "stack.py",
    "web.py",
    "analyze",
]


def main() -> int:
    session = make_session_factory(make_engine())()
    try:
        snapshot = export_snapshot(session)
        drugs = sorted(set(_ingested_drugs(session)))
    finally:
        session.close()

    if LIB.exists():
        shutil.rmtree(LIB)
    (LIB / "ssa").mkdir(parents=True)
    for name in MODULES:
        src = ROOT / "src" / "ssa" / name
        dst = LIB / "ssa" / name
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    shutil.copy2(ROOT / "data" / "unit_conversions.csv", LIB / "ssa" / "unit_conversions.csv")
    (LIB / "graph.json").write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")

    kinds = [e["kind"] for e in snapshot["entities"]]
    stats = {
        "INTERACTIONS": len(snapshot["interactions"]),
        "SEVERE": sum(
            i["severity"] in ("MAJOR", "CONTRAINDICATED") for i in snapshot["interactions"]
        ),
        "SUPPLEMENTS": sum(k in ("NUTRIENT", "HERBAL") for k in kinds),
        "DRUG_NAMES": len(snapshot["aliases"]),
        "LIMITS": len(snapshot["upper_limits"]),
        "DRUG_COUNT": len(drugs),
        "DRUG_LIST": ", ".join(d.capitalize() for d in drugs),
    }
    template = (SITE / "template" / "index.html").read_text(encoding="utf-8")
    for key, value in stats.items():
        template = template.replace("{{" + key + "}}", html.escape(str(value)))
    if "{{" in template:
        raise SystemExit("unfilled placeholder left in template")
    (SITE / "public" / "index.html").write_text(template, encoding="utf-8")

    print(f"Snapshot: {stats['INTERACTIONS']} interactions, {len(kinds)} entities.")
    print(f"Drugs read: {stats['DRUG_LIST']}")
    print(f"Wrote {LIB} and site/public/index.html")
    return 0


def _ingested_drugs(session) -> list[str]:
    from sqlalchemy import select

    from ssa.models import PipelineRun

    return [
        run.stats["drug"]
        for run in session.scalars(select(PipelineRun)).all()
        if isinstance(run.stats, dict) and run.stats.get("drug")
    ]


if __name__ == "__main__":
    raise SystemExit(main())

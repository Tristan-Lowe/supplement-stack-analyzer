"""Resolve ingredient names from real supplement labels the resolver has never seen.

The hand-written gold set measures what its author thought to test, and the same
author wrote the synonyms, so a perfect score there is partly a measure of
self-consistency. Ingredient names pulled from NIH DSLD labels are written by
manufacturers, not by us. Nothing here has an expected answer in advance: the
output is a list of (raw, resolved-to) pairs to be labelled by hand, and the
number that matters is how many resolved to the WRONG entity.

    python -m evals.run_dsld_heldout out.json "query one" "query two" ...
"""

from __future__ import annotations

import json
import logging
import sys

from ssa.connectors.dsld import fetch_label, search_labels
from ssa.db import make_engine, make_session_factory
from ssa.models import Entity
from ssa.resolver import Ambiguous, Resolved, build_alias_index, resolve

LABELS_PER_QUERY = 4


def collect_names(queries: list[str]) -> dict[str, str]:
    """Unique ingredient names across the labels each query returns."""
    names: dict[str, str] = {}
    for query in queries:
        for dsld_id, _ in search_labels(query, limit=LABELS_PER_QUERY):
            label = fetch_label(dsld_id)
            if label is None:
                continue
            for name in [i.name for i in label.ingredients] + label.unquantified:
                names.setdefault(name, query)
    return names


def main(argv: list[str]) -> int:
    logging.disable(logging.WARNING)
    out_path, queries = argv[0], argv[1:]
    names = collect_names(queries)

    session = make_session_factory(make_engine())()
    index = build_alias_index(session)
    rows = []
    for name in sorted(names):
        result = resolve(session, name, alias_index=index)
        if isinstance(result, Resolved):
            resolved = session.get(Entity, result.entity_id).canonical_name
            via = result.matched_via
        elif isinstance(result, Ambiguous):
            resolved = "AMBIGUOUS: " + ", ".join(
                session.get(Entity, i).canonical_name for i in result.candidate_ids
            )
            via = "ambiguous"
        else:
            resolved, via = None, "unknown"
        rows.append({"raw": name, "query": names[name], "resolved": resolved, "via": via})
    session.close()

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    hit = sum(r["resolved"] is not None for r in rows)
    print(f"{len(rows)} unique ingredient names, {hit} resolved -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

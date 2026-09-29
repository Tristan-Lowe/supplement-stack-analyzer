import json

from evals.run_interaction_eval import evaluate, load_gold
from ssa.extract.gates import merge_triple
from ssa.models import EntityKind, EvidenceGrade, Severity
from ssa.registry import get_or_create_entity
from ssa.review import approve

SPAN = "Ginkgo may increase the risk of bleeding with warfarin."


def test_every_gold_row_carries_a_source_and_quote():
    rows = load_gold()
    assert len(rows) >= 40
    for row in rows:
        assert row["source_url"].startswith("https://")
        assert row["quote"].strip()


def test_gold_quotes_are_verbatim_in_their_cached_source():
    """The builder enforces this; the test keeps a hand edit from slipping past it."""
    from evals.build_interaction_gold import ROWS

    by_pair = {(a, b): (cache, quote) for a, b, cache, _url, quote, _note in ROWS}
    for row in load_gold():
        cache, quote = by_pair[(row["a"], row["b"])]
        text = open(f"evals/cache/{cache}.txt", encoding="utf-8").read()
        assert quote in text, (row["a"], row["b"])


def test_recall_counts_found_and_splits_misses(session):
    warfarin = get_or_create_entity(session, EntityKind.DRUG, "Warfarin")
    ginkgo = get_or_create_entity(session, EntityKind.HERBAL, "Ginkgo Biloba")
    get_or_create_entity(session, EntityKind.HERBAL, "Garlic")
    session.commit()
    row = merge_triple(
        session, entity_a_id=ginkgo.id, entity_b_id=warfarin.id, mechanism="Bleeding.",
        direction="increases_toxicity_risk", severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.C, span=SPAN, source="openfda",
        source_url="https://api.fda.gov/x", source_text=SPAN,
    )
    approve(session, row.id, reviewer="test")
    gold = [
        {"a": "Ginkgo Biloba", "b": "warfarin", "significant": True},
        {"a": "Garlic", "b": "warfarin", "significant": True},
        {"a": "Flibbertigibbet", "b": "warfarin", "significant": True},
    ]

    report = evaluate(session, json.loads(json.dumps(gold)))

    assert (report.total, report.found) == (3, 1)
    assert report.no_edge == ["Garlic + warfarin"]
    assert len(report.unrecognised) == 1

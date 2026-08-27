from evals.run_resolution_eval import GoldCase, evaluate, load_gold
from ssa.models import EntityKind
from ssa.registry import add_alias, get_or_create_entity


def test_load_gold_reads_all_cases():
    cases = load_gold("evals/resolution_gold.jsonl")
    assert len(cases) >= 20
    assert isinstance(cases[0], GoldCase)


def test_evaluate_scores_a_tiny_registry(session):
    magnesium = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")
    add_alias(session, magnesium, "magnesium bisglycinate", source="test")
    get_or_create_entity(session, EntityKind.NUTRIENT, "Manganese")

    cases = [
        GoldCase(raw="Magnesium Bisglycinate", expected="Magnesium", note=""),
        GoldCase(raw="manganese", expected="Manganese", note=""),
        GoldCase(raw="Vitamin B", expected=None, note=""),
    ]

    report = evaluate(session, cases)

    assert report.total == 3
    assert report.correct == 3
    assert report.accuracy == 1.0
    assert report.failures == []

"""Curated kind classification. Whole-token matching only — never substrings."""

from ssa.bootstrap import classify_kind
from ssa.models import EntityKind
from ssa.registry import get_or_create_entity, reclassify_entities


def test_known_nutrients_and_herbals():
    assert classify_kind("Vitamin K") is EntityKind.NUTRIENT
    assert classify_kind("Biotin") is EntityKind.NUTRIENT
    assert classify_kind("St. John's Wort Extract") is EntityKind.HERBAL
    assert classify_kind("Ginkgo Biloba Extract") is EntityKind.HERBAL
    assert classify_kind("Garlic Preparation") is EntityKind.HERBAL


def test_rxnorm_suffixes_are_stripped_before_lookup():
    """RxNorm returns "Ginseng Preparation"; the curated entry is "ginseng"."""
    assert classify_kind("Ginseng Preparation") is EntityKind.HERBAL
    assert classify_kind("Ginseng") is EntityKind.HERBAL


def test_vitamin_prefix_is_a_whole_token_rule():
    assert classify_kind("Vitamin B12") is EntityKind.NUTRIENT
    assert classify_kind("Vitamin D") is EntityKind.NUTRIENT


def test_substring_collisions_do_not_misclassify():
    """"Buspirone" contains "iron". Substring matching here would be a real bug."""
    assert classify_kind("Buspirone") is EntityKind.DRUG
    assert classify_kind("Warfarin") is EntityKind.DRUG
    assert classify_kind("Levothyroxine") is EntityKind.DRUG


def test_unknown_compounds_default_to_drug():
    """Safer default: calling a drug a supplement could imply it is benign."""
    assert classify_kind("Flibbertigibbet") is EntityKind.DRUG


def test_reclassify_fixes_entities_ingested_before_classification(session):
    wort = get_or_create_entity(session, EntityKind.DRUG, "St. John's Wort Extract")
    warfarin = get_or_create_entity(session, EntityKind.DRUG, "Warfarin")
    session.commit()

    changed = reclassify_entities(session)

    assert ("St. John's Wort Extract", "drug", "herbal") in changed
    assert session.get(type(wort), wort.id).kind is EntityKind.HERBAL
    assert session.get(type(warfarin), warfarin.id).kind is EntityKind.DRUG


def test_reclassify_never_downgrades_a_seeded_nutrient(session):
    nutrient = get_or_create_entity(session, EntityKind.NUTRIENT, "Manganese")
    session.commit()

    reclassify_entities(session)

    assert session.get(type(nutrient), nutrient.id).kind is EntityKind.NUTRIENT

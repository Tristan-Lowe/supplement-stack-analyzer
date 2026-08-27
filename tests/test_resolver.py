from ssa.models import EntityKind
from ssa.registry import add_alias, get_or_create_entity
from ssa.resolver import Ambiguous, Resolved, Unknown, resolve


def test_exact_alias_match(session):
    entity = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")
    add_alias(session, entity, "Magnesium Bisglycinate", source="dsld")

    result = resolve(session, "Magnesium Bisglycinate")

    assert isinstance(result, Resolved)
    assert result.entity_id == entity.id
    assert result.matched_via == "alias"


def test_salt_stripped_match(session):
    entity = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")

    result = resolve(session, "Magnesium Threonate")

    assert isinstance(result, Resolved)
    assert result.entity_id == entity.id
    assert result.matched_via == "salt_stripped"


def test_fuzzy_match_on_typo(session):
    entity = get_or_create_entity(session, EntityKind.HERBAL, "Ashwagandha")

    result = resolve(session, "ashwaganda")

    assert isinstance(result, Resolved)
    assert result.entity_id == entity.id
    assert result.matched_via == "fuzzy"


def test_ambiguous_when_multiple_entities_share_an_alias(session):
    nutrient = get_or_create_entity(session, EntityKind.NUTRIENT, "Potassium")
    drug = get_or_create_entity(session, EntityKind.DRUG, "Potassium Chloride")
    add_alias(session, nutrient, "potassium", source="ods")
    add_alias(session, drug, "potassium", source="rxnorm")

    result = resolve(session, "potassium")

    assert isinstance(result, Ambiguous)
    assert sorted(result.candidate_ids) == sorted([nutrient.id, drug.id])


def test_unknown_when_nothing_matches(session):
    get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")

    result = resolve(session, "flibbertigibbet extract")

    assert isinstance(result, Unknown)
    assert result.raw == "flibbertigibbet extract"


def test_vague_input_is_not_guessed(session):
    get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin B12")
    get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin B6")

    result = resolve(session, "Vitamin B")

    assert not isinstance(result, Resolved)


def test_fuzzy_below_threshold_is_unknown(session):
    get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")

    result = resolve(session, "manganese")

    assert isinstance(result, Unknown)

from ssa.models import EntityKind
from ssa.registry import add_alias, find_by_alias, get_or_create_entity, list_aliases


def test_get_or_create_is_idempotent(session):
    first = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")
    second = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")
    assert first.id == second.id


def test_same_name_different_kind_are_distinct(session):
    nutrient = get_or_create_entity(session, EntityKind.NUTRIENT, "Potassium")
    drug = get_or_create_entity(session, EntityKind.DRUG, "Potassium")
    assert nutrient.id != drug.id


def test_add_alias_normalizes_and_is_idempotent(session):
    entity = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")
    add_alias(session, entity, "Mag Glycinate", source="user")
    add_alias(session, entity, "mag  glycinate", source="dsld")

    aliases = list_aliases(session, entity)
    # Both surface forms normalize to "magnesium glycinate" and collapse to one row.
    glycinate = [a for a in aliases if a.normalized_alias == "magnesium glycinate"]
    assert len(glycinate) == 1
    # The other row is the canonical name, registered by get_or_create_entity.
    assert len(aliases) == 2


def test_find_by_alias_matches_normalized_form(session):
    entity = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")
    add_alias(session, entity, "Magnesium Bisglycinate", source="dsld")
    found = find_by_alias(session, "  magnesium   bisglycinate ")
    assert [e.id for e in found] == [entity.id]


def test_find_by_alias_returns_all_matches(session):
    nutrient = get_or_create_entity(session, EntityKind.NUTRIENT, "Potassium")
    drug = get_or_create_entity(session, EntityKind.DRUG, "Potassium Chloride")
    add_alias(session, nutrient, "potassium", source="ods")
    add_alias(session, drug, "potassium", source="rxnorm")
    found = find_by_alias(session, "Potassium")
    assert len(found) == 2


def test_canonical_name_is_registered_as_an_alias(session):
    entity = get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin D3")
    found = find_by_alias(session, "vitamin d3")
    assert [e.id for e in found] == [entity.id]

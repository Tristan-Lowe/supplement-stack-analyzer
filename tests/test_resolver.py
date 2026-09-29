from ssa.models import EntityKind
from ssa.registry import add_alias, get_or_create_entity
from ssa.resolver import Ambiguous, Resolved, Unknown, build_alias_index, resolve


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


# --- Fuzzy stage must reason about entities, not alias strings ---


def test_shared_alias_reached_by_fuzzy_is_ambiguous_not_guessed(session):
    """Two entities owning the same alias must not collapse to whichever came last.

    Keying candidates by alias string silently drops one entity, turning a genuine
    ambiguity into a confident wrong answer — the exact failure this component
    exists to prevent. Exact matching catches the no-typo case, so only the fuzzy
    path exercises this.
    """
    nutrient = get_or_create_entity(session, EntityKind.NUTRIENT, "Potassium")
    drug = get_or_create_entity(session, EntityKind.DRUG, "Potassium Chloride")
    add_alias(session, nutrient, "potassium gluconate", source="ods")
    add_alias(session, drug, "potassium gluconate", source="rxnorm")
    session.commit()

    result = resolve(session, "potassium gluconatte")  # typo forces the fuzzy path

    assert isinstance(result, Ambiguous)
    assert sorted(result.candidate_ids) == sorted([nutrient.id, drug.id])


def test_many_aliases_of_one_entity_do_not_hide_a_rival(session):
    """A popular entity's aliases must not crowd a genuine near-tie out of the window."""
    popular = get_or_create_entity(session, EntityKind.NUTRIENT, "Ashwagandha")
    for alias in [
        "ashwagandha root", "ashwagandha extract", "ashwagandha powder",
        "ashwagandha ksm66", "ashwagandha sensoril", "ashwagandha capsule",
        "ashwagandha roott", "ashwagandha roots", "ashwagandha extractt",
    ]:
        add_alias(session, popular, alias, source="test")

    rival = get_or_create_entity(session, EntityKind.HERBAL, "Ashwagandha Root Powder")
    session.commit()

    result = resolve(session, "ashwagandha rootx")

    # Either outcome is defensible; silently resolving to the popular entity while
    # the rival never entered the comparison is not.
    if isinstance(result, Resolved):
        assert result.entity_id in {popular.id, rival.id}
    else:
        assert isinstance(result, Ambiguous)
        assert rival.id in result.candidate_ids


# --- The indexed path and the database path must not diverge ---


def test_index_path_agrees_with_database_path(session):
    """Two implementations of one contract is a bug waiting to happen.

    build_alias_index() exists purely for speed. If it ever disagrees with the
    direct database path, resolution silently depends on which caller you are.
    """
    magnesium = get_or_create_entity(session, EntityKind.NUTRIENT, "Magnesium")
    add_alias(session, magnesium, "Magnesium Bisglycinate", source="dsld")
    get_or_create_entity(session, EntityKind.NUTRIENT, "Manganese")
    get_or_create_entity(session, EntityKind.HERBAL, "Ashwagandha")
    potassium = get_or_create_entity(session, EntityKind.NUTRIENT, "Potassium")
    kcl = get_or_create_entity(session, EntityKind.DRUG, "Potassium Chloride")
    add_alias(session, potassium, "potassium", source="ods")
    add_alias(session, kcl, "potassium", source="rxnorm")
    session.commit()

    index = build_alias_index(session)

    probes = [
        "Magnesium Bisglycinate",   # exact alias
        "Magnesium Threonate",      # salt-stripped
        "ashwaganda",               # fuzzy
        "manganese",                # must stay unknown
        "potassium",                # ambiguous
        "Vitamin B",                # vague
        "flibbertigibbet extract",  # unknown
    ]

    for probe in probes:
        from_db = resolve(session, probe)
        from_index = resolve(session, probe, alias_index=index)
        assert type(from_db) is type(from_index), probe
        if isinstance(from_db, Resolved):
            assert from_db.entity_id == from_index.entity_id, probe
            assert from_db.matched_via == from_index.matched_via, probe
        if isinstance(from_db, Ambiguous):
            assert sorted(from_db.candidate_ids) == sorted(from_index.candidate_ids), probe


# --- Guards against confident wrong answers ---


def test_numbered_vitamin_does_not_fuzzy_match_its_neighbour(session):
    """B5 is not B6. Edit distance scores them 90; the numbers must agree."""
    get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin B6")
    session.commit()

    assert isinstance(resolve(session, "vitamin b5"), Unknown)
    assert isinstance(resolve(session, "vitamin b6"), Resolved)


def test_combination_line_does_not_collapse_to_one_nutrient(session):
    get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin D3")
    session.commit()

    assert isinstance(resolve(session, "vitamin d3 + k2"), Unknown)


def test_a_drug_never_wins_a_fuzzy_match(session):
    """escitalopram scores 91 against citalopram. They are different drugs."""
    get_or_create_entity(session, EntityKind.DRUG, "Citalopram")
    session.commit()

    assert isinstance(resolve(session, "escitalopram"), Unknown)
    assert isinstance(resolve(session, "citalopram"), Resolved)


def test_supplement_misspelling_still_fuzzy_matches(session):
    turmeric = get_or_create_entity(session, EntityKind.HERBAL, "Turmeric")
    session.commit()

    result = resolve(session, "tumeric")

    assert isinstance(result, Resolved)
    assert result.entity_id == turmeric.id
    assert result.matched_via == "fuzzy"

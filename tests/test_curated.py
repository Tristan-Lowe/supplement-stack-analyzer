import pytest

from ssa.curated import load_supplement_registry, renormalize_aliases
from ssa.models import Entity, EntityAlias, EntityKind, Interaction, Severity, UpperLimit
from ssa.registry import add_alias, get_or_create_entity
from ssa.resolver import Resolved, resolve


def _write(tmp_path, body: str):
    path = tmp_path / "registry.csv"
    path.write_text("canonical_name,kind,aliases,note\n" + body, encoding="utf-8")
    return path


def test_creates_entity_with_aliases(session, tmp_path):
    csv_path = _write(tmp_path, "Creatine,NUTRIENT,creatine monohydrate|creatine hcl,\n")

    report = load_supplement_registry(session, csv_path)

    assert report.created == 1
    result = resolve(session, "creatine monohydrate")
    assert isinstance(result, Resolved)
    assert session.get(Entity, result.entity_id).canonical_name == "Creatine"


def test_is_idempotent(session, tmp_path):
    csv_path = _write(tmp_path, "Creatine,NUTRIENT,creatine monohydrate,\n")
    load_supplement_registry(session, csv_path)

    again = load_supplement_registry(session, csv_path)

    assert again.created == 0
    assert again.aliases == 0
    assert again.merged == []


def test_absorbs_named_bootstrap_duplicate_and_keeps_its_interactions(session, tmp_path):
    """A bootstrap "St. John's Wort Extract" becomes the clean curated entity."""
    extract = get_or_create_entity(session, EntityKind.HERBAL, "St. John's Wort Extract")
    warfarin = get_or_create_entity(session, EntityKind.DRUG, "Warfarin")
    low, high = sorted((extract.id, warfarin.id))
    session.add(
        Interaction(
            entity_a_id=low,
            entity_b_id=high,
            mechanism="CYP induction",
            direction="decreases",
            severity=Severity.MAJOR,
            evidence_grade="B",
        )
    )
    session.commit()
    csv_path = _write(
        tmp_path, "St. John's Wort,HERBAL,hypericum|St. John's Wort Extract,\n"
    )

    report = load_supplement_registry(session, csv_path)

    assert report.merged == [("St. John's Wort Extract", "St. John's Wort")]
    assert session.get(Entity, extract.id) is None
    result = resolve(session, "St. John's Wort Extract")
    assert isinstance(result, Resolved)
    curated = session.get(Entity, result.entity_id)
    assert curated.canonical_name == "St. John's Wort"
    interaction = session.query(Interaction).one()
    assert curated.id in (interaction.entity_a_id, interaction.entity_b_id)


def test_absorbs_across_kinds(session, tmp_path):
    """Bootstrap filed Tryptophan as a drug; the curated row reclassifies it."""
    get_or_create_entity(session, EntityKind.DRUG, "Tryptophan")
    session.commit()
    csv_path = _write(tmp_path, "Tryptophan,NUTRIENT,l tryptophan,\n")

    load_supplement_registry(session, csv_path)

    entities = session.query(Entity).filter(Entity.canonical_name == "Tryptophan").all()
    assert [e.kind for e in entities] == [EntityKind.NUTRIENT]


def test_does_not_merge_by_similarity(session, tmp_path):
    """Only a duplicate the CSV names is absorbed. Similar names are left alone."""
    get_or_create_entity(session, EntityKind.HERBAL, "Siberian Ginseng")
    session.commit()
    csv_path = _write(tmp_path, "Ginseng,HERBAL,panax ginseng,\n")

    load_supplement_registry(session, csv_path)

    assert session.query(Entity).count() == 2


def test_refuses_alias_owned_by_unrelated_entity(session, tmp_path):
    drug = get_or_create_entity(session, EntityKind.DRUG, "Potassium Chloride")
    add_alias(session, drug, "potassium gluconate", source="rxnorm")
    session.commit()
    csv_path = _write(tmp_path, "Potassium,NUTRIENT,potassium gluconate,\n")

    with pytest.raises(ValueError, match="already owned"):
        load_supplement_registry(session, csv_path)


def test_refuses_to_absorb_an_entity_with_an_upper_limit(session, tmp_path):
    """Absorbing a seeded nutrient would delete its toxicity ceiling."""
    d3 = get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin D3")
    session.add(
        UpperLimit(
            entity_id=d3.id, amount=100, unit="mcg", population="adult",
            basis="x", source_url="https://example.org",
        )
    )
    session.commit()
    csv_path = _write(tmp_path, "Vitamin D,NUTRIENT,Vitamin D3,\n")

    with pytest.raises(ValueError, match="upper limit"):
        load_supplement_registry(session, csv_path)


def test_renormalize_repairs_keys_computed_by_older_normalization(session):
    k = get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin K")
    stale = EntityAlias(
        entity_id=k.id, alias="Vitamin K2", normalized_alias="vitamin vitamin k2",
        source="old",
    )
    session.add(stale)
    session.commit()

    changed = renormalize_aliases(session)

    assert changed == 1
    assert stale.normalized_alias == "vitamin k2"
    assert isinstance(resolve(session, "vitamin k2"), Resolved)


def test_shipped_registry_loads_cleanly(session):
    report = load_supplement_registry(session)

    assert report.created >= 30

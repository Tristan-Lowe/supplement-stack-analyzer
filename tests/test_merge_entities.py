"""Folding a bootstrap-created duplicate back into its seeded nutrient."""

import pytest
from sqlalchemy import select

from ssa.connectors.ods import load_nutrient_synonyms, load_upper_limits
from ssa.extract.gates import merge_triple
from ssa.models import Entity, EntityKind, Evidence, EvidenceGrade, Interaction, Severity
from ssa.registry import (
    add_alias,
    find_nutrient_duplicates,
    get_or_create_entity,
    merge_entities,
)
from ssa.resolver import Resolved, resolve

SOURCE = "Cholecalciferol interacts with warfarin. Vitamin D affects calcium."


def test_finds_a_drug_named_after_a_nutrient_synonym(session):
    load_upper_limits(session, "data/upper_limits.csv")
    load_nutrient_synonyms(session, "data/nutrient_synonyms.csv")
    dupe = get_or_create_entity(session, EntityKind.DRUG, "Cholecalciferol")
    session.commit()

    found = find_nutrient_duplicates(session)

    assert any(d == dupe.id and name == "Cholecalciferol" for d, _, name in found)


def test_merge_moves_aliases_and_resolves_unambiguously(session):
    load_upper_limits(session, "data/upper_limits.csv")
    load_nutrient_synonyms(session, "data/nutrient_synonyms.csv")
    dupe = get_or_create_entity(session, EntityKind.DRUG, "Cholecalciferol")
    add_alias(session, dupe, "vitamin d3 softgel", source="rxnorm")
    session.commit()
    canonical = session.scalars(
        select(Entity).where(Entity.canonical_name == "Vitamin D3")
    ).one()

    # Before: two entities claim the name, so the resolver refuses to choose.
    assert not isinstance(resolve(session, "cholecalciferol"), Resolved)

    merge_entities(session, dupe.id, canonical.id)

    result = resolve(session, "cholecalciferol")
    assert isinstance(result, Resolved)
    assert result.entity_id == canonical.id
    assert isinstance(resolve(session, "vitamin d3 softgel"), Resolved)
    assert session.get(Entity, dupe.id) is None


def test_merge_repoints_interactions(session):
    load_upper_limits(session, "data/upper_limits.csv")
    dupe = get_or_create_entity(session, EntityKind.DRUG, "Cholecalciferol")
    warfarin = get_or_create_entity(session, EntityKind.DRUG, "Warfarin")
    session.commit()
    canonical = session.scalars(
        select(Entity).where(Entity.canonical_name == "Vitamin D3")
    ).one()

    merge_triple(
        session, entity_a_id=dupe.id, entity_b_id=warfarin.id,
        mechanism="m", direction="unclear", severity=Severity.MINOR,
        evidence_grade=EvidenceGrade.C, span="Cholecalciferol interacts with warfarin.",
        source="openfda", source_url="https://example.test/1", source_text=SOURCE,
    )

    merge_entities(session, dupe.id, canonical.id)

    row = session.scalars(select(Interaction)).one()
    assert sorted([row.entity_a_id, row.entity_b_id]) == sorted([canonical.id, warfarin.id])
    assert len(session.scalars(select(Evidence)).all()) == 1


def test_colliding_interactions_merge_their_evidence(session):
    """Both entities already interact with warfarin — evidence must survive."""
    load_upper_limits(session, "data/upper_limits.csv")
    dupe = get_or_create_entity(session, EntityKind.DRUG, "Cholecalciferol")
    warfarin = get_or_create_entity(session, EntityKind.DRUG, "Warfarin")
    session.commit()
    canonical = session.scalars(
        select(Entity).where(Entity.canonical_name == "Vitamin D3")
    ).one()

    common = dict(
        mechanism="m", direction="unclear", severity=Severity.MINOR,
        evidence_grade=EvidenceGrade.C, source="openfda", source_text=SOURCE,
    )
    merge_triple(session, entity_a_id=dupe.id, entity_b_id=warfarin.id,
                 span="Cholecalciferol interacts with warfarin.",
                 source_url="https://example.test/1", **common)
    merge_triple(session, entity_a_id=canonical.id, entity_b_id=warfarin.id,
                 span="Vitamin D affects calcium.",
                 source_url="https://example.test/2", **common)

    merge_entities(session, dupe.id, canonical.id)

    assert len(session.scalars(select(Interaction)).all()) == 1
    assert len(session.scalars(select(Evidence)).all()) == 2


def test_cannot_merge_into_itself(session):
    entity = get_or_create_entity(session, EntityKind.DRUG, "Warfarin")
    session.commit()

    with pytest.raises(ValueError, match="into itself"):
        merge_entities(session, entity.id, entity.id)

"""Chemical synonyms must resolve to the seeded nutrient, not spawn a duplicate.

The duplicate is not cosmetic. Only seeded nutrients carry UpperLimit rows, so a
compound that resolves to a bootstrap-created twin silently gets no toxicity
ceiling check.
"""

import pytest
from sqlalchemy import select

from ssa.analyze.limits import check_upper_limits
from ssa.analyze.redundancy import ResolvedDose
from ssa.connectors.ods import load_nutrient_synonyms, load_upper_limits
from ssa.models import Entity, EntityKind
from ssa.resolver import Resolved, resolve


def seeded(session):
    load_upper_limits(session, "data/upper_limits.csv")
    load_nutrient_synonyms(session, "data/nutrient_synonyms.csv")


def test_chemical_names_resolve_to_the_seeded_nutrient(session):
    seeded(session)

    for surface, expected in [
        ("cholecalciferol", "Vitamin D3"),
        ("pyridoxine", "Vitamin B6"),
        ("ferrous sulfate", "Iron"),
        ("alpha tocopherol", "Vitamin E"),
        ("folic acid", "Folate"),
        ("calcium carbonate", "Calcium"),
    ]:
        result = resolve(session, surface)
        assert isinstance(result, Resolved), f"{surface} did not resolve"
        entity = session.get(Entity, result.entity_id)
        assert entity.canonical_name == expected, f"{surface} -> {entity.canonical_name}"
        assert entity.kind is EntityKind.NUTRIENT


def test_synonym_inherits_the_upper_limit_check(session):
    """The reason this matters: the ceiling must fire on the chemical name too."""
    seeded(session)

    result = resolve(session, "pyridoxine")
    assert isinstance(result, Resolved)

    findings = check_upper_limits(
        session,
        [
            ResolvedDose(
                entity_id=result.entity_id, amount=150.0, unit="mg",
                source_label="B Complex",
            )
        ],
    )

    assert len(findings) == 1
    assert "neuropathy" in findings[0].detail


def test_loading_synonyms_is_idempotent(session):
    load_upper_limits(session, "data/upper_limits.csv")
    first = load_nutrient_synonyms(session, "data/nutrient_synonyms.csv")
    second = load_nutrient_synonyms(session, "data/nutrient_synonyms.csv")

    assert first > 0
    assert second == 0


def test_synonym_without_a_seeded_nutrient_is_an_error(session, tmp_path):
    """A silent skip would leave a gap nobody notices."""
    bad = tmp_path / "bad.csv"
    bad.write_text("canonical_name,synonym,note\nNonexistent,foo,x\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no seeded nutrient"):
        load_nutrient_synonyms(session, bad)


def test_no_duplicate_entity_is_created(session):
    seeded(session)
    before = len(session.scalars(select(Entity)).all())

    load_nutrient_synonyms(session, "data/nutrient_synonyms.csv")

    assert len(session.scalars(select(Entity)).all()) == before

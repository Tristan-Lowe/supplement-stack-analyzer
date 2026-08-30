"""Registry bootstrap. RxNorm is mocked — no test makes a network call."""

from unittest.mock import MagicMock, patch

import responses
from sqlalchemy import select

from ssa.bootstrap import bootstrap_entity
from ssa.connectors.rxnorm import RXNORM_BASE, DrugConcept, lookup_ingredient
from ssa.extract.schema import CandidateTriple, ExtractionResult
from ssa.models import Entity, EntityKind, EvidenceGrade, Interaction, Severity
from ssa.pipeline import ingest_section
from ssa.registry import get_or_create_entity
from ssa.resolver import Resolved, resolve


@responses.activate
def test_lookup_ingredient_collapses_brand_to_ingredient():
    """Synthroid and levothyroxine must not become two entities."""
    responses.add(
        responses.GET, f"{RXNORM_BASE}/rxcui.json",
        json={"idGroup": {"rxnormId": ["224920"]}}, status=200,
    )
    responses.add(
        responses.GET, f"{RXNORM_BASE}/rxcui/224920/property.json",
        json={"propConceptGroup": {"propConcept": [
            {"propName": "RxNorm Name", "propValue": "Synthroid"}]}}, status=200,
    )
    responses.add(
        responses.GET, f"{RXNORM_BASE}/rxcui/224920/related.json",
        json={"relatedGroup": {"conceptGroup": [
            {"tty": "IN", "conceptProperties": [
                {"rxcui": "10582", "name": "levothyroxine"}]}]}}, status=200,
    )

    concept = lookup_ingredient("Synthroid")

    assert concept == DrugConcept(rxcui="10582", name="levothyroxine")


def test_bootstrap_creates_entity_and_aliases_the_surface_form(session):
    with patch(
        "ssa.bootstrap.lookup_ingredient",
        return_value=DrugConcept(rxcui="10582", name="levothyroxine"),
    ):
        entity = bootstrap_entity(session, "levothyroxine sodium tablets")

    assert entity is not None
    assert entity.canonical_name == "Levothyroxine"
    assert entity.rxcui == "10582"
    # The surface form now resolves offline — every bootstrap improves the resolver.
    assert isinstance(resolve(session, "levothyroxine sodium tablets"), Resolved)


def test_bootstrap_returns_none_when_rxnorm_does_not_know_the_name(session):
    with patch("ssa.bootstrap.lookup_ingredient", return_value=None):
        assert bootstrap_entity(session, "flibbertigibbet extract") is None
    assert session.scalars(select(Entity)).all() == []


def test_three_surface_forms_collapse_to_one_entity(session):
    with patch(
        "ssa.bootstrap.lookup_ingredient",
        return_value=DrugConcept(rxcui="10582", name="levothyroxine"),
    ):
        for surface in ["Synthroid", "levothyroxine sodium tablets", "Levothyroxine"]:
            bootstrap_entity(session, surface)

    assert len(session.scalars(select(Entity)).all()) == 1


def test_pipeline_bootstraps_then_stores(session):
    """The end-to-end gap: a fresh registry quarantined everything."""
    get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    session.commit()

    source = "Calcium carbonate may bind levothyroxine and reduce its absorption."
    client = MagicMock()
    client.messages.parse.return_value = MagicMock(
        parsed_output=ExtractionResult(triples=[CandidateTriple(
            compound_a="Calcium carbonate", compound_b="levothyroxine sodium tablets",
            mechanism="Binding reduces absorption.",
            direction="decreases_absorption_of_b",
            severity=Severity.MODERATE, evidence_grade=EvidenceGrade.B,
            span=source,
        )])
    )

    with patch(
        "ssa.bootstrap.lookup_ingredient",
        return_value=DrugConcept(rxcui="10582", name="levothyroxine"),
    ):
        stats = ingest_section(session, client, source, "openfda", "https://example.test/1")

    assert stats["stored"] == 1
    assert stats["quarantined"] == 0
    assert stats["bootstrapped"] == 1
    assert len(session.scalars(select(Interaction)).all()) == 1

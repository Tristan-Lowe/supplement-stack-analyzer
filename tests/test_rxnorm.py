import responses

from ssa.connectors.rxnorm import RXNORM_BASE, DrugConcept, lookup_drug


@responses.activate
def test_lookup_drug_returns_concept():
    responses.add(
        responses.GET,
        f"{RXNORM_BASE}/rxcui.json",
        json={"idGroup": {"rxnormId": ["36567"]}},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{RXNORM_BASE}/rxcui/36567/property.json",
        json={"propConceptGroup": {"propConcept": [{"propName": "RxNorm Name",
                                                    "propValue": "simvastatin"}]}},
        status=200,
    )

    concept = lookup_drug("Zocor")

    assert isinstance(concept, DrugConcept)
    assert concept.rxcui == "36567"
    assert concept.name == "simvastatin"


@responses.activate
def test_lookup_drug_returns_none_when_not_found():
    responses.add(
        responses.GET,
        f"{RXNORM_BASE}/rxcui.json",
        json={"idGroup": {}},
        status=200,
    )

    assert lookup_drug("flibbertigibbet") is None


@responses.activate
def test_lookup_drug_returns_none_on_server_error():
    responses.add(responses.GET, f"{RXNORM_BASE}/rxcui.json", status=500)

    assert lookup_drug("aspirin") is None

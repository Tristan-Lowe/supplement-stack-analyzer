"""Connectors must degrade, never crash.

Every connector documents that it returns an empty result on failure. That
contract is load-bearing: the analysis engine treats "empty" as *no data
retrieved* and says so to the user, whereas an uncaught exception surfaces as a
crash. A malformed 200 response is the realistic failure these guard against —
the HTTP call succeeds, so the request-level try/except never fires.
"""

import responses

from ssa.connectors.dsld import DSLD_BASE, fetch_label, search_labels
from ssa.connectors.openfda import OPENFDA_BASE, fetch_interaction_sections
from ssa.connectors.rxnorm import RXNORM_BASE, lookup_drug


@responses.activate
def test_rxnorm_survives_non_json_body():
    responses.add(
        responses.GET, f"{RXNORM_BASE}/rxcui.json", body="<html>gateway error</html>", status=200
    )

    assert lookup_drug("aspirin") is None


@responses.activate
def test_rxnorm_falls_back_to_input_name_when_property_body_is_junk():
    responses.add(
        responses.GET, f"{RXNORM_BASE}/rxcui.json",
        json={"idGroup": {"rxnormId": ["36567"]}}, status=200,
    )
    responses.add(
        responses.GET, f"{RXNORM_BASE}/rxcui/36567/property.json",
        body="not json", status=200,
    )

    concept = lookup_drug("Zocor")

    assert concept is not None
    assert concept.rxcui == "36567"
    assert concept.name == "Zocor"


@responses.activate
def test_openfda_survives_non_json_body():
    responses.add(
        responses.GET, f"{OPENFDA_BASE}/drug/label.json", body="upstream failure", status=200
    )

    assert fetch_interaction_sections("levothyroxine") == []


@responses.activate
def test_dsld_search_skips_hit_without_id():
    responses.add(
        responses.GET, f"{DSLD_BASE}/search-filter",
        json={
            "hits": [
                {"_source": {"fullName": "No Id Here"}},
                {"_id": "123", "_source": {"fullName": "Basic B Complex"}},
            ]
        },
        status=200,
    )

    assert search_labels("anything") == [("123", "Basic B Complex")]


@responses.activate
def test_dsld_search_survives_non_json_body():
    responses.add(responses.GET, f"{DSLD_BASE}/search-filter", body="nope", status=200)

    assert search_labels("anything") == []


@responses.activate
def test_dsld_label_records_unusable_quantity_as_unquantified():
    """A "trace" amount or a missing unit must not lose the whole label."""
    responses.add(
        responses.GET, f"{DSLD_BASE}/label/789",
        json={
            "fullName": "Messy Label",
            "brandName": "Acme",
            "ingredientRows": [
                {"name": "Boron", "quantity": [{"quantity": "trace", "unit": "mg"}]},
                {"name": "Silica", "quantity": [{"quantity": 10.0}]},
                {"name": "Zinc", "quantity": [{"quantity": 15.0, "unit": "mg"}]},
            ],
        },
        status=200,
    )

    label = fetch_label("789")

    assert label is not None
    assert [i.name for i in label.ingredients] == ["Zinc"]
    assert sorted(label.unquantified) == ["Boron", "Silica"]


@responses.activate
def test_dsld_label_survives_non_json_body():
    responses.add(responses.GET, f"{DSLD_BASE}/label/789", body="<html>", status=200)

    assert fetch_label("789") is None

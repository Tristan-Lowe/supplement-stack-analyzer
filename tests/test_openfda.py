import responses

from ssa.connectors.openfda import OPENFDA_BASE, DrugLabelSection, fetch_interaction_sections


@responses.activate
def test_fetch_interaction_sections_returns_text():
    responses.add(
        responses.GET,
        f"{OPENFDA_BASE}/drug/label.json",
        json={
            "results": [
                {
                    "id": "abc-123",
                    "openfda": {"generic_name": ["LEVOTHYROXINE SODIUM"]},
                    "drug_interactions": [
                        "Calcium carbonate and magnesium may bind levothyroxine and "
                        "reduce its absorption. Separate administration by 4 hours."
                    ],
                }
            ]
        },
        status=200,
    )

    sections = fetch_interaction_sections("levothyroxine")

    assert len(sections) == 1
    section = sections[0]
    assert isinstance(section, DrugLabelSection)
    assert section.generic_name == "LEVOTHYROXINE SODIUM"
    assert "Separate administration by 4 hours." in section.text
    assert section.source_url.endswith("abc-123")


@responses.activate
def test_fetch_skips_results_without_interaction_section():
    responses.add(
        responses.GET,
        f"{OPENFDA_BASE}/drug/label.json",
        json={"results": [{"id": "no-int", "openfda": {"generic_name": ["ASPIRIN"]}}]},
        status=200,
    )

    assert fetch_interaction_sections("aspirin") == []


@responses.activate
def test_fetch_returns_empty_on_error():
    responses.add(responses.GET, f"{OPENFDA_BASE}/drug/label.json", status=404)

    assert fetch_interaction_sections("nothing") == []

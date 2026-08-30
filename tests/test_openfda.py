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


@responses.activate
def test_citation_url_is_escaped_and_falls_back_without_an_id():
    """Citation links are the trust surface; a broken one reads as sloppiness."""
    responses.add(
        responses.GET,
        f"{OPENFDA_BASE}/drug/label.json",
        json={
            "results": [
                {
                    "id": "abc 123/xyz",
                    "openfda": {"generic_name": ["LEVOTHYROXINE SODIUM"]},
                    "drug_interactions": ["Calcium may bind levothyroxine."],
                },
                {
                    "openfda": {"generic_name": ["WARFARIN SODIUM"]},
                    "drug_interactions": ["Vitamin K opposes warfarin."],
                },
            ]
        },
        status=200,
    )

    sections = fetch_interaction_sections("anything")

    assert len(sections) == 2
    # The id contained a space and a slash; neither may appear raw in the URL.
    assert " " not in sections[0].source_url
    assert "id:abc%20123%2Fxyz" in sections[0].source_url
    # No id at all: fall back to a name query rather than emit a dangling "id:".
    assert not sections[1].source_url.endswith("id:")
    assert "generic_name" in sections[1].source_url

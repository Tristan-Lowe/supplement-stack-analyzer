import responses

from ssa.connectors.dsld import (
    DSLD_BASE,
    LabelIngredient,
    SupplementLabel,
    fetch_label,
    search_labels,
)


@responses.activate
def test_search_labels_returns_hits():
    responses.add(
        responses.GET,
        f"{DSLD_BASE}/search-filter",
        json={"hits": [{"_id": "123", "_source": {"fullName": "Basic B Complex"}}]},
        status=200,
    )

    hits = search_labels("Basic B Complex")

    assert hits == [("123", "Basic B Complex")]


@responses.activate
def test_fetch_label_expands_ingredients():
    responses.add(
        responses.GET,
        f"{DSLD_BASE}/label/123",
        json={
            "fullName": "Basic B Complex",
            "brandName": "Thorne",
            "ingredientRows": [
                {"name": "Thiamin", "quantity": [{"quantity": 100.0, "unit": "mg"}]},
                {"name": "Vitamin B6", "quantity": [{"quantity": 10.0, "unit": "mg"}]},
            ],
        },
        status=200,
    )

    label = fetch_label("123")

    assert isinstance(label, SupplementLabel)
    assert label.brand == "Thorne"
    assert label.ingredients == [
        LabelIngredient(name="Thiamin", amount=100.0, unit="mg"),
        LabelIngredient(name="Vitamin B6", amount=10.0, unit="mg"),
    ]


@responses.activate
def test_fetch_label_skips_ingredients_without_quantity():
    responses.add(
        responses.GET,
        f"{DSLD_BASE}/label/456",
        json={
            "fullName": "Proprietary Blend",
            "brandName": "Acme",
            "ingredientRows": [
                {"name": "Green Tea Extract", "quantity": []},
                {"name": "Zinc", "quantity": [{"quantity": 15.0, "unit": "mg"}]},
            ],
        },
        status=200,
    )

    label = fetch_label("456")

    assert label.ingredients == [LabelIngredient(name="Zinc", amount=15.0, unit="mg")]
    assert label.unquantified == ["Green Tea Extract"]


@responses.activate
def test_fetch_label_returns_none_on_error():
    responses.add(responses.GET, f"{DSLD_BASE}/label/999", status=404)

    assert fetch_label("999") is None

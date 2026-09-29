import responses

from ssa.bootstrap import enrich_drug_aliases
from ssa.connectors.rxnorm import RXNORM_BASE
from ssa.models import EntityKind
from ssa.registry import add_alias, get_or_create_entity
from ssa.resolver import Resolved, Unknown, resolve


def _related(rxcui: str, tty: str, concepts: list[tuple[str, str, str]]):
    """Register a related.json response. RxNorm returns one group per term type."""
    groups: dict[str, list[dict]] = {}
    for cid, name, ctype in concepts:
        groups.setdefault(ctype, []).append({"rxcui": cid, "name": name, "tty": ctype})
    responses.add(
        responses.GET,
        f"{RXNORM_BASE}/rxcui/{rxcui}/related.json",
        match=[responses.matchers.query_param_matcher({"tty": tty})],
        json={
            "relatedGroup": {
                "conceptGroup": [
                    {"tty": t, "conceptProperties": props} for t, props in groups.items()
                ]
            }
        },
    )


def _atorvastatin(session):
    entity = get_or_create_entity(session, EntityKind.DRUG, "Atorvastatin", rxcui="83367")
    session.commit()
    return entity


@responses.activate
def test_adds_single_ingredient_brand_and_salt_form(session):
    atorvastatin = _atorvastatin(session)
    _related(
        "83367",
        "BN PIN",
        [("153165", "Lipitor", "BN"), ("83366", "atorvastatin calcium", "PIN")],
    )
    _related("153165", "IN", [("83367", "atorvastatin", "IN")])

    added = enrich_drug_aliases(session, atorvastatin)

    assert sorted(added) == ["Lipitor", "atorvastatin calcium"]
    result = resolve(session, "Lipitor")
    assert isinstance(result, Resolved)
    assert result.entity_id == atorvastatin.id


@responses.activate
def test_refuses_combination_brand(session):
    """Caduet is atorvastatin + amlodipine. It must not become atorvastatin."""
    atorvastatin = _atorvastatin(session)
    _related("83367", "BN PIN", [("404914", "Caduet", "BN")])
    _related(
        "404914",
        "IN",
        [("83367", "atorvastatin", "IN"), ("17767", "amlodipine", "IN")],
    )

    added = enrich_drug_aliases(session, atorvastatin)

    assert added == []
    assert isinstance(resolve(session, "Caduet"), Unknown)


@responses.activate
def test_failed_ingredient_lookup_is_a_refusal(session):
    atorvastatin = _atorvastatin(session)
    _related("83367", "BN PIN", [("153165", "Lipitor", "BN")])
    responses.add(
        responses.GET, f"{RXNORM_BASE}/rxcui/153165/related.json", status=503
    )

    assert enrich_drug_aliases(session, atorvastatin) == []


@responses.activate
def test_skips_alias_owned_by_another_entity(session):
    atorvastatin = _atorvastatin(session)
    other = get_or_create_entity(session, EntityKind.DRUG, "Something Else")
    add_alias(session, other, "Lipitor", source="test")
    session.commit()
    _related("83367", "BN PIN", [("153165", "Lipitor", "BN")])
    _related("153165", "IN", [("83367", "atorvastatin", "IN")])

    assert enrich_drug_aliases(session, atorvastatin) == []


def test_ignores_non_drugs_and_drugs_without_rxcui(session):
    garlic = get_or_create_entity(session, EntityKind.HERBAL, "Garlic", rxcui="265647")
    mystery = get_or_create_entity(session, EntityKind.DRUG, "Mystery")
    session.commit()

    assert enrich_drug_aliases(session, garlic) == []
    assert enrich_drug_aliases(session, mystery) == []

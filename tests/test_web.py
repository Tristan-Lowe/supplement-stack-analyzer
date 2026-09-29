import json

from ssa.extract.gates import merge_triple
from ssa.models import EntityKind, EvidenceGrade, Severity
from ssa.registry import add_alias, get_or_create_entity
from ssa.review import approve
from ssa.web import (
    RateLimiter,
    export_snapshot,
    handle_analyze,
    load_snapshot,
    safe_citation_url,
)

LABEL = "https://api.fda.gov/drug/label.json?search=id:abc"
SPAN = "Some botanicals may decrease the effects of warfarin (e.g., St. John's wort)."


def seed(session):
    warfarin = get_or_create_entity(session, EntityKind.DRUG, "Warfarin")
    add_alias(session, warfarin, "Coumadin", source="rxnorm_brand")
    sjw = get_or_create_entity(session, EntityKind.HERBAL, "St. John's Wort")
    ginkgo = get_or_create_entity(session, EntityKind.HERBAL, "Ginkgo Biloba")
    session.commit()
    published = merge_triple(
        session, entity_a_id=sjw.id, entity_b_id=warfarin.id, mechanism="Induction.",
        direction="decreases_effect_of_b", severity=Severity.MAJOR,
        evidence_grade=EvidenceGrade.C, span=SPAN, source="openfda",
        source_url=LABEL, source_text=SPAN,
    )
    approve(session, published.id, reviewer="test")
    merge_triple(  # stays pending: must never reach the snapshot
        session, entity_a_id=ginkgo.id, entity_b_id=warfarin.id, mechanism="Bleeding.",
        direction="increases_toxicity_risk", severity=Severity.MAJOR,
        evidence_grade=EvidenceGrade.C, span=SPAN, source="openfda",
        source_url=LABEL, source_text=SPAN,
    )


def roundtrip(session, tmp_path):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(export_snapshot(session)), encoding="utf-8")
    return load_snapshot(path)()


def post(session, text, **kw):
    body = json.dumps({"text": text}).encode()
    args = {"content_type": "application/json", "origin": None, "host": None} | kw
    return handle_analyze(session, body, **args)


def test_snapshot_excludes_pending_interactions(session):
    seed(session)
    snap = export_snapshot(session)
    assert len(snap["interactions"]) == 1
    assert snap["interactions"][0]["severity"] == "MAJOR"


def test_snapshot_roundtrip_answers_like_the_source(session, tmp_path):
    seed(session)
    snap_session = roundtrip(session, tmp_path)

    status, payload = post(snap_session, "Coumadin 5mg, St Johns Wort 300mg")

    assert status == 200
    assert payload["identified"] == 2
    [finding] = payload["findings"]
    assert finding["severity"] == "major"
    assert finding["citations"][0]["url"] == LABEL
    assert finding["citations"][0]["label"] == "FDA drug label"


def test_pending_interaction_is_not_served(session, tmp_path):
    seed(session)
    status, payload = post(roundtrip(session, tmp_path), "warfarin, ginkgo")
    assert status == 200
    assert payload["findings"] == []
    assert "No known interactions" in payload["summary"]


def test_response_never_claims_safety(session, tmp_path):
    seed(session)
    _, payload = post(roundtrip(session, tmp_path), "ginkgo")
    text = json.dumps(payload).lower()
    assert "safe" not in text.replace("safety", "")


def test_unidentified_items_are_listed_not_dropped(session, tmp_path):
    seed(session)
    _, payload = post(roundtrip(session, tmp_path), "warfarin, flibbertigibbet")
    assert payload["unidentified"] == ["flibbertigibbet"]


def test_rejects_cross_origin_and_wrong_type(session):
    status, _ = post(session, "x", origin="https://evil.example", host="site.example")
    assert status == 403
    status, _ = post(session, "x", content_type="text/plain")
    assert status == 415


def test_rejects_malformed_empty_and_oversized(session):
    assert handle_analyze(session, b"{not json", "application/json", None, None)[0] == 400
    assert handle_analyze(session, b'{"text": 5}', "application/json", None, None)[0] == 400
    assert post(session, "   ")[0] == 422
    assert post(session, "a" * 2_001)[0] == 413
    assert post(session, ",".join(["zinc"] * 41))[0] == 413


def test_error_messages_do_not_echo_input(session):
    _, payload = post(session, "<script>alert(1)</script>" * 100)
    assert "<script>" not in payload["error"]


def test_citation_urls_are_allowlisted():
    assert safe_citation_url(LABEL) == LABEL
    assert safe_citation_url("https://ods.od.nih.gov/factsheets/x/") is not None
    for bad in (
        "javascript:alert(1)",
        "http://api.fda.gov/x",
        "https://api.fda.gov.evil.com/x",
        "https://user@api.fda.gov/x",
        "https://evil.com/?u=https://api.fda.gov",
        " not a url",
    ):
        assert safe_citation_url(bad) is None, bad


def test_rate_limiter_blocks_after_limit_and_recovers():
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert all(limiter.allow("1.2.3.4", now=t) for t in (0, 1, 2))
    assert not limiter.allow("1.2.3.4", now=3)
    assert limiter.allow("5.6.7.8", now=3)
    assert limiter.allow("1.2.3.4", now=70)

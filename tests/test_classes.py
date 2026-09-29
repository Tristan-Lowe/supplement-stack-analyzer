import json

import responses

from ssa.analyze.engine import analyze_stack
from ssa.analyze.pairwise import check_pairwise
from ssa.classes import load_drug_classes
from ssa.connectors.rxclass import RXCLASS_BASE, ClassMember, class_members
from ssa.extract.gates import merge_triple
from ssa.models import ClassMembership, EntityKind, EvidenceGrade, Severity
from ssa.registry import get_or_create_entity, merge_entities
from ssa.resolver import Resolved, resolve
from ssa.review import approve
from ssa.web import export_snapshot, load_snapshot

SPAN = "NSAIDs may potentiate the risk of bleeding with SSRIs."


def _csv(tmp_path):
    path = tmp_path / "classes.csv"
    path.write_text(
        "canonical_name,atc_codes,aliases,note\n"
        "NSAIDs,M01A,nsaids|nonsteroidal anti-inflammatory drugs,\n",
        encoding="utf-8",
    )
    return path


def _fetch(code):
    return {
        "M01A": [ClassMember("5640", "ibuprofen"), ClassMember("7258", "naproxen")],
    }.get(code, [])


def _publish(session, a, b, severity=Severity.MAJOR, mechanism="Bleeding risk."):
    row = merge_triple(
        session, entity_a_id=a.id, entity_b_id=b.id, mechanism=mechanism,
        direction="increases_toxicity_risk", severity=severity,
        evidence_grade=EvidenceGrade.B, span=SPAN, source="openfda",
        source_url="https://api.fda.gov/drug/label.json?search=id:x", source_text=SPAN,
    )
    approve(session, row.id, reviewer="test")
    return row


def test_loader_creates_class_members_and_aliases(session, tmp_path):
    report = load_drug_classes(session, _csv(tmp_path), fetch=_fetch)

    assert (report.classes, report.memberships, report.new_drugs) == (1, 2, 2)
    result = resolve(session, "Nonsteroidal anti-inflammatory drugs")
    assert isinstance(result, Resolved)
    assert load_drug_classes(session, _csv(tmp_path), fetch=_fetch).memberships == 0


def test_loader_reuses_an_existing_entity_by_rxcui(session, tmp_path):
    existing = get_or_create_entity(session, EntityKind.DRUG, "Ibuprofen", rxcui="5640")
    session.commit()

    report = load_drug_classes(session, _csv(tmp_path), fetch=_fetch)

    assert report.new_drugs == 1  # only naproxen
    assert session.query(ClassMembership).filter_by(member_id=existing.id).count() == 1


def test_failed_lookup_is_reported_not_treated_as_empty(session, tmp_path):
    report = load_drug_classes(session, _csv(tmp_path), fetch=lambda code: None)
    assert report.failed_codes == ["M01A"]


def test_class_warning_reaches_a_member_drug(session, tmp_path):
    load_drug_classes(session, _csv(tmp_path), fetch=_fetch)
    nsaids = get_or_create_entity(session, EntityKind.CLASS, "NSAIDs")
    sertraline = get_or_create_entity(session, EntityKind.DRUG, "Sertraline")
    ibuprofen = get_or_create_entity(session, EntityKind.DRUG, "Ibuprofen")
    session.commit()
    _publish(session, nsaids, sertraline)

    [finding] = check_pairwise(session, [sertraline.id, ibuprofen.id])

    assert finding.severity is Severity.MAJOR
    assert "Ibuprofen" in finding.title and "Sertraline" in finding.title
    assert "NSAIDs" in finding.detail


def test_direct_edge_wins_over_class_edge(session, tmp_path):
    load_drug_classes(session, _csv(tmp_path), fetch=_fetch)
    nsaids = get_or_create_entity(session, EntityKind.CLASS, "NSAIDs")
    sertraline = get_or_create_entity(session, EntityKind.DRUG, "Sertraline")
    ibuprofen = get_or_create_entity(session, EntityKind.DRUG, "Ibuprofen")
    session.commit()
    _publish(session, nsaids, sertraline, severity=Severity.MAJOR, mechanism="Class.")
    _publish(session, ibuprofen, sertraline, severity=Severity.MODERATE, mechanism="Direct.")

    [finding] = check_pairwise(session, [sertraline.id, ibuprofen.id])

    assert finding.detail == "Direct."


def test_a_class_typed_by_the_user_is_not_checked(session, tmp_path):
    load_drug_classes(session, _csv(tmp_path), fetch=_fetch)

    report = analyze_stack(session, "NSAIDs, naproxen")

    assert report.unresolved == ["NSAIDs"]
    assert report.resolved_count == 1


def test_merge_moves_memberships(session, tmp_path):
    load_drug_classes(session, _csv(tmp_path), fetch=_fetch)
    ibuprofen = resolve(session, "ibuprofen")
    advil = get_or_create_entity(session, EntityKind.DRUG, "Ibuprofen Tablet")
    session.commit()

    merge_entities(session, ibuprofen.entity_id, advil.id)

    assert session.query(ClassMembership).filter_by(member_id=advil.id).count() == 1


def test_snapshot_carries_class_findings(session, tmp_path):
    load_drug_classes(session, _csv(tmp_path), fetch=_fetch)
    nsaids = get_or_create_entity(session, EntityKind.CLASS, "NSAIDs")
    sertraline = get_or_create_entity(session, EntityKind.DRUG, "Sertraline")
    session.commit()
    _publish(session, nsaids, sertraline)
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(export_snapshot(session)), encoding="utf-8")

    with load_snapshot(path)() as snap:
        report = analyze_stack(snap, "sertraline, naproxen")

    assert len(report.findings) == 1


@responses.activate
def test_connector_skips_combination_members():
    responses.add(
        responses.GET,
        f"{RXCLASS_BASE}/classMembers.json",
        json={"drugMemberGroup": {"drugMember": [
            {"minConcept": {"rxcui": "612", "name": "aluminum hydroxide"}},
            {"minConcept": {"rxcui": "9", "name": "aluminum hydroxide / magnesium carbonate"}},
        ]}},
    )

    members = class_members("A02A")

    assert [m.name for m in members] == ["aluminum hydroxide"]


@responses.activate
def test_connector_failure_returns_none():
    responses.add(responses.GET, f"{RXCLASS_BASE}/classMembers.json", status=503)
    assert class_members("A02A") is None

from ssa.analyze.findings import FindingKind
from ssa.analyze.timing import check_timing, seed_timing_rule
from ssa.models import EntityKind, Severity
from ssa.registry import get_or_create_entity


def seed(session):
    calcium = get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    levo = get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()
    seed_timing_rule(
        session,
        entity_a_id=calcium.id,
        entity_b_id=levo.id,
        separation_hours=4.0,
        note="Calcium binds levothyroxine in the gut; separate doses by at least 4 hours.",
        source_url="https://example.test/levo",
    )
    return calcium, levo


def test_finds_timing_rule(session):
    calcium, levo = seed(session)

    findings = check_timing(session, [calcium.id, levo.id])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind is FindingKind.TIMING
    assert finding.severity is Severity.MODERATE
    assert "4" in finding.detail
    assert sorted(finding.entity_ids) == sorted([calcium.id, levo.id])


def test_pair_order_does_not_matter(session):
    calcium, levo = seed(session)

    assert len(check_timing(session, [levo.id, calcium.id])) == 1


def test_seed_timing_rule_is_idempotent(session):
    calcium, levo = seed(session)

    seed_timing_rule(
        session,
        entity_a_id=levo.id,
        entity_b_id=calcium.id,
        separation_hours=4.0,
        note="duplicate",
        source_url="https://example.test/levo",
    )

    assert len(check_timing(session, [calcium.id, levo.id])) == 1


def test_no_rule_produces_no_finding(session):
    zinc = get_or_create_entity(session, EntityKind.NUTRIENT, "Zinc")
    copper = get_or_create_entity(session, EntityKind.NUTRIENT, "Copper")
    session.commit()

    assert check_timing(session, [zinc.id, copper.id]) == []


def test_single_entity_produces_no_finding(session):
    calcium, _ = seed(session)

    assert check_timing(session, [calcium.id]) == []

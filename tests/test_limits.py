from sqlalchemy import select

from ssa.analyze.findings import FindingKind
from ssa.analyze.limits import check_upper_limits
from ssa.analyze.redundancy import ResolvedDose
from ssa.connectors.ods import load_upper_limits
from ssa.models import Entity, EntityKind, Severity
from ssa.registry import get_or_create_entity


def b6_id(session) -> int:
    load_upper_limits(session, "data/upper_limits.csv")
    return session.scalars(select(Entity).where(Entity.canonical_name == "Vitamin B6")).one().id


def test_flags_cumulative_breach(session):
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session,
        [
            ResolvedDose(entity_id=entity_id, amount=60.0, unit="mg", source_label="Multi"),
            ResolvedDose(entity_id=entity_id, amount=60.0, unit="mg", source_label="B Complex"),
        ],
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind is FindingKind.UPPER_LIMIT
    assert finding.severity is Severity.MAJOR
    assert "120" in finding.detail
    assert "100" in finding.detail
    assert "neuropathy" in finding.detail
    assert finding.citations[0].source_url.startswith("https://ods.od.nih.gov")


def test_under_limit_is_not_flagged(session):
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=entity_id, amount=25.0, unit="mg", source_label="Multi")]
    )

    assert findings == []


def test_mismatched_unit_is_never_converted(session):
    """A mcg dose against an mg limit must not be converted — but must not go silent."""
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=entity_id, amount=5000.0, unit="mcg", source_label="X")]
    )

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.UNRESOLVED
    assert findings[0].kind is not FindingKind.UPPER_LIMIT
    assert "X" in findings[0].detail


def test_missing_amount_is_reported_not_silently_skipped(session):
    """Silence would read as an all-clear. Say what could not be assessed."""
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=entity_id, amount=None, unit=None, source_label="X")]
    )

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.UNRESOLVED
    assert "could not be fully assessed" in findings[0].title


def test_measurable_portion_over_limit_is_a_certain_breach(session):
    """If the known part alone exceeds the ceiling, the unknown part cannot rescue it."""
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session,
        [
            ResolvedDose(entity_id=entity_id, amount=120.0, unit="mg", source_label="B Complex"),
            ResolvedDose(entity_id=entity_id, amount=None, unit=None, source_label="Multi"),
        ],
    )

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.UPPER_LIMIT
    assert findings[0].severity is Severity.MAJOR
    assert "real total is higher" in findings[0].detail


def test_partial_assessment_under_limit_does_not_claim_safety(session):
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session,
        [
            ResolvedDose(entity_id=entity_id, amount=95.0, unit="mg", source_label="B Complex"),
            ResolvedDose(entity_id=entity_id, amount=None, unit=None, source_label="Multi"),
        ],
    )

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.UNRESOLVED
    assert "Multi" in findings[0].detail
    assert "safe" not in findings[0].detail.lower()


def test_entity_without_a_known_limit_is_skipped(session):
    ashwagandha = get_or_create_entity(session, EntityKind.HERBAL, "Ashwagandha")
    session.commit()

    findings = check_upper_limits(
        session,
        [ResolvedDose(entity_id=ashwagandha.id, amount=600.0, unit="mg", source_label="X")],
    )

    assert findings == []


def _entity_id(session, name):
    load_upper_limits(session, "data/upper_limits.csv")
    return session.scalars(select(Entity).where(Entity.canonical_name == name)).one().id


def test_vitamin_d_iu_converts_exactly_and_breaches_the_limit(session):
    """5000 IU is 125 mcg, over the 100 mcg limit. One of the most common doses sold."""
    d3 = _entity_id(session, "Vitamin D3")

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=d3, amount=5000.0, unit="iu", source_label="Vitamin D")]
    )

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.UPPER_LIMIT
    assert findings[0].severity is Severity.MAJOR
    assert "125 mcg" in findings[0].detail
    assert "5000 IU" in findings[0].detail


def test_vitamin_d_iu_and_mcg_sum_together(session):
    d3 = _entity_id(session, "Vitamin D3")

    findings = check_upper_limits(
        session,
        [
            ResolvedDose(entity_id=d3, amount=2000.0, unit="iu", source_label="Vitamin D"),
            ResolvedDose(entity_id=d3, amount=60.0, unit="mcg", source_label="Multivitamin"),
        ],
    )

    assert findings[0].kind is FindingKind.UPPER_LIMIT  # 50 + 60 = 110 mcg
    assert "110 mcg" in findings[0].detail


def test_vitamin_d_iu_under_the_limit_is_not_flagged(session):
    d3 = _entity_id(session, "Vitamin D3")

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=d3, amount=2000.0, unit="iu", source_label="Vitamin D")]
    )

    assert findings == []


def test_vitamin_a_iu_is_still_not_converted(session):
    """Retinol and beta-carotene IU convert differently. Never guess."""
    a = _entity_id(session, "Vitamin A")

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=a, amount=20000.0, unit="iu", source_label="Vitamin A")]
    )

    assert findings[0].kind is FindingKind.UNRESOLVED

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


def test_mismatched_unit_is_skipped_not_guessed(session):
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=entity_id, amount=5000.0, unit="mcg", source_label="X")]
    )

    assert findings == []


def test_missing_amount_is_skipped(session):
    entity_id = b6_id(session)

    findings = check_upper_limits(
        session, [ResolvedDose(entity_id=entity_id, amount=None, unit=None, source_label="X")]
    )

    assert findings == []


def test_entity_without_a_known_limit_is_skipped(session):
    ashwagandha = get_or_create_entity(session, EntityKind.HERBAL, "Ashwagandha")
    session.commit()

    findings = check_upper_limits(
        session,
        [ResolvedDose(entity_id=ashwagandha.id, amount=600.0, unit="mg", source_label="X")],
    )

    assert findings == []

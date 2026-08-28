from ssa.analyze.findings import FindingKind
from ssa.analyze.redundancy import ResolvedDose, check_redundancy
from ssa.models import EntityKind, Severity
from ssa.registry import get_or_create_entity


def test_flags_same_entity_from_multiple_products(session):
    b6 = get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin B6")
    session.commit()

    findings = check_redundancy(
        session,
        [
            ResolvedDose(entity_id=b6.id, amount=50.0, unit="mg", source_label="Multivitamin"),
            ResolvedDose(entity_id=b6.id, amount=100.0, unit="mg", source_label="B Complex"),
        ],
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind is FindingKind.REDUNDANCY
    assert finding.entity_ids == [b6.id]
    assert "Multivitamin" in finding.detail
    assert "B Complex" in finding.detail
    assert "150" in finding.detail


def test_single_source_is_not_redundant(session):
    b6 = get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin B6")
    session.commit()

    findings = check_redundancy(
        session, [ResolvedDose(entity_id=b6.id, amount=50.0, unit="mg", source_label="Multi")]
    )

    assert findings == []


def test_mismatched_units_still_flag_but_omit_total(session):
    d3 = get_or_create_entity(session, EntityKind.NUTRIENT, "Vitamin D3")
    session.commit()

    findings = check_redundancy(
        session,
        [
            ResolvedDose(entity_id=d3.id, amount=25.0, unit="mcg", source_label="Multi"),
            ResolvedDose(entity_id=d3.id, amount=2000.0, unit="iu", source_label="D3 softgel"),
        ],
    )

    assert len(findings) == 1
    assert "different units" in findings[0].detail


def test_redundancy_severity_is_minor(session):
    zinc = get_or_create_entity(session, EntityKind.NUTRIENT, "Zinc")
    session.commit()

    findings = check_redundancy(
        session,
        [
            ResolvedDose(entity_id=zinc.id, amount=15.0, unit="mg", source_label="A"),
            ResolvedDose(entity_id=zinc.id, amount=15.0, unit="mg", source_label="B"),
        ],
    )

    assert findings[0].severity is Severity.MINOR

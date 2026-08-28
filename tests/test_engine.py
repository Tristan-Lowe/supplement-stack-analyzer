from ssa.analyze.engine import AnalysisReport, analyze_stack
from ssa.analyze.findings import FindingKind
from ssa.analyze.timing import seed_timing_rule
from ssa.connectors.ods import load_upper_limits
from ssa.extract.gates import merge_triple
from ssa.models import SEVERITY_RANK, EntityKind, EvidenceGrade, InteractionStatus, Severity
from ssa.registry import add_alias, get_or_create_entity

SOURCE_TEXT = "Calcium may bind levothyroxine. Separate doses by 4 hours."


def seed_world(session):
    load_upper_limits(session, "data/upper_limits.csv")
    calcium = get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    levo = get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    add_alias(session, levo, "Synthroid", source="rxnorm")
    session.commit()

    interaction = merge_triple(
        session,
        entity_a_id=calcium.id,
        entity_b_id=levo.id,
        mechanism="Calcium binds levothyroxine and reduces its absorption.",
        direction="decreases_absorption_of_b",
        severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B,
        span="Calcium may bind levothyroxine.",
        source="openfda",
        source_url="https://example.test/1",
        source_text=SOURCE_TEXT,
    )
    interaction.status = InteractionStatus.PUBLISHED
    session.commit()

    seed_timing_rule(
        session,
        entity_a_id=calcium.id,
        entity_b_id=levo.id,
        separation_hours=4.0,
        note="Separate doses by at least 4 hours.",
        source_url="https://example.test/1",
    )
    return calcium, levo


def test_end_to_end_finds_interaction_and_timing(session):
    seed_world(session)

    report = analyze_stack(session, "Calcium 500mg\nSynthroid 100mcg")

    assert isinstance(report, AnalysisReport)
    kinds = {f.kind for f in report.findings}
    assert FindingKind.INTERACTION in kinds
    assert FindingKind.TIMING in kinds
    assert report.resolved_count == 2
    assert report.unresolved == []


def test_findings_are_ranked_most_severe_first(session):
    seed_world(session)

    report = analyze_stack(
        session, "Calcium 500mg\nSynthroid 100mcg\nVitamin B6 60mg, Vitamin B6 60mg"
    )

    ranks = [SEVERITY_RANK[f.severity] for f in report.findings]
    assert ranks == sorted(ranks, reverse=True)
    assert report.findings[0].severity is Severity.MAJOR


def test_unresolved_compound_becomes_a_finding(session):
    seed_world(session)

    report = analyze_stack(session, "Calcium 500mg\nflibbertigibbet extract 100mg")

    assert report.unresolved == ["flibbertigibbet extract"]
    unresolved = [
        f for f in report.findings
        if f.kind is FindingKind.UNRESOLVED and "flibbertigibbet" in f.detail
    ]
    assert len(unresolved) == 1


def test_summary_never_claims_safety(session):
    seed_world(session)

    report = analyze_stack(session, "Calcium 500mg")

    assert report.findings == []
    assert "safe" not in report.summary.lower()
    assert "no known interactions" in report.summary.lower()
    assert "1" in report.summary


def test_upper_limit_breach_is_reported(session):
    seed_world(session)

    report = analyze_stack(session, "Vitamin B6 60mg, Vitamin B6 60mg")

    limit_findings = [f for f in report.findings if f.kind is FindingKind.UPPER_LIMIT]
    assert len(limit_findings) == 1
    assert limit_findings[0].severity is Severity.MAJOR


def test_ambiguous_input_is_reported_as_unresolved(session):
    seed_world(session)
    nutrient = get_or_create_entity(session, EntityKind.NUTRIENT, "Potassium")
    drug = get_or_create_entity(session, EntityKind.DRUG, "Potassium Chloride")
    add_alias(session, nutrient, "potassium", source="ods")
    add_alias(session, drug, "potassium", source="rxnorm")
    session.commit()

    report = analyze_stack(session, "potassium 99mg")

    assert report.unresolved == ["potassium"]


def test_disclaimer_is_always_present(session):
    seed_world(session)

    report = analyze_stack(session, "Calcium 500mg")

    assert "not medical advice" in report.disclaimer.lower()

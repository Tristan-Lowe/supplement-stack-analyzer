from ssa.analyze.findings import FindingKind, Tier
from ssa.analyze.pairwise import check_pairwise
from ssa.extract.gates import merge_triple
from ssa.models import EntityKind, EvidenceGrade, InteractionStatus, Severity
from ssa.registry import get_or_create_entity

SOURCE_TEXT = "Calcium may bind levothyroxine. Separate doses by 4 hours."


def seed_interaction(session, status=InteractionStatus.PUBLISHED):
    calcium = get_or_create_entity(session, EntityKind.NUTRIENT, "Calcium")
    levo = get_or_create_entity(session, EntityKind.DRUG, "Levothyroxine")
    session.commit()
    interaction = merge_triple(
        session,
        entity_a_id=calcium.id,
        entity_b_id=levo.id,
        mechanism="Calcium binds levothyroxine and reduces absorption.",
        direction="decreases_absorption_of_b",
        severity=Severity.MODERATE,
        evidence_grade=EvidenceGrade.B,
        span="Calcium may bind levothyroxine.",
        source="openfda",
        source_url="https://example.test/1",
        source_text=SOURCE_TEXT,
    )
    interaction.status = status
    session.commit()
    return calcium, levo


def test_finds_published_interaction(session):
    calcium, levo = seed_interaction(session)

    findings = check_pairwise(session, [calcium.id, levo.id])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind is FindingKind.INTERACTION
    assert finding.severity is Severity.MODERATE
    assert finding.tier is Tier.GRAPH
    assert sorted(finding.entity_ids) == sorted([calcium.id, levo.id])
    assert finding.citations[0].source_url == "https://example.test/1"


def test_pair_order_does_not_matter(session):
    calcium, levo = seed_interaction(session)

    assert len(check_pairwise(session, [levo.id, calcium.id])) == 1


def test_pending_review_interactions_are_not_returned(session):
    calcium, levo = seed_interaction(session, status=InteractionStatus.PENDING_REVIEW)

    assert check_pairwise(session, [calcium.id, levo.id]) == []


def test_no_findings_when_only_one_entity(session):
    calcium, _ = seed_interaction(session)

    assert check_pairwise(session, [calcium.id]) == []


def test_unrelated_entities_produce_nothing(session):
    seed_interaction(session)
    zinc = get_or_create_entity(session, EntityKind.NUTRIENT, "Zinc")
    copper = get_or_create_entity(session, EntityKind.NUTRIENT, "Copper")
    session.commit()

    assert check_pairwise(session, [zinc.id, copper.id]) == []

from ssa.models import (
    Entity,
    EntityAlias,
    EntityKind,
    EvidenceGrade,
    Interaction,
    InteractionStatus,
    Severity,
)


def test_entity_round_trip(session):
    entity = Entity(kind=EntityKind.NUTRIENT, canonical_name="Magnesium")
    session.add(entity)
    session.commit()

    loaded = session.query(Entity).one()
    assert loaded.canonical_name == "Magnesium"
    assert loaded.kind is EntityKind.NUTRIENT
    assert loaded.id is not None


def test_alias_links_to_entity(session):
    entity = Entity(kind=EntityKind.NUTRIENT, canonical_name="Magnesium")
    session.add(entity)
    session.flush()
    session.add(
        EntityAlias(
            entity_id=entity.id,
            alias="Magnesium Bisglycinate",
            normalized_alias="magnesium bisglycinate",
            source="dsld",
        )
    )
    session.commit()

    alias = session.query(EntityAlias).one()
    assert alias.entity_id == entity.id


def test_interaction_stores_enums(session):
    a = Entity(kind=EntityKind.NUTRIENT, canonical_name="Magnesium")
    b = Entity(kind=EntityKind.DRUG, canonical_name="Levothyroxine")
    session.add_all([a, b])
    session.flush()

    session.add(
        Interaction(
            entity_a_id=a.id,
            entity_b_id=b.id,
            mechanism="Chelation reduces levothyroxine absorption.",
            direction="decreases_effect_of_b",
            severity=Severity.MODERATE,
            evidence_grade=EvidenceGrade.B,
            confidence=0.8,
            status=InteractionStatus.PENDING_REVIEW,
        )
    )
    session.commit()

    row = session.query(Interaction).one()
    assert row.severity is Severity.MODERATE
    assert row.evidence_grade is EvidenceGrade.B
    assert row.status is InteractionStatus.PENDING_REVIEW

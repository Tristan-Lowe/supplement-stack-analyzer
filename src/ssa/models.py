from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class EntityKind(enum.StrEnum):
    NUTRIENT = "nutrient"
    HERBAL = "herbal"
    DRUG = "drug"
    OTHER = "other"


class Severity(enum.StrEnum):
    """Clinical consequence if the pair is taken together."""

    CONTRAINDICATED = "contraindicated"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"
    THEORETICAL = "theoretical"


class EvidenceGrade(enum.StrEnum):
    """Strength of underlying evidence, independent of severity."""

    A = "A"  # human RCT or systematic review
    B = "B"  # human observational, case series, or PK study
    C = "C"  # case reports or drug-class extrapolation
    D = "D"  # in vitro, animal, or mechanistic inference only


class InteractionStatus(enum.StrEnum):
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.CONTRAINDICATED: 5,
    Severity.MAJOR: 4,
    Severity.MODERATE: 3,
    Severity.MINOR: 2,
    Severity.THEORETICAL: 1,
}

REVIEW_REQUIRED_AT_OR_ABOVE = SEVERITY_RANK[Severity.MODERATE]


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[EntityKind] = mapped_column(Enum(EntityKind), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rxcui: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unii: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    aliases: Mapped[list[EntityAlias]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("kind", "canonical_name", name="uq_entity_kind_name"),
        Index("ix_entity_rxcui", "rxcui"),
    )


class EntityAlias(Base):
    __tablename__ = "entity_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    entity: Mapped[Entity] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_alias", name="uq_alias_entity_norm"),
        Index("ix_alias_normalized", "normalized_alias"),
    )


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_a_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    entity_b_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(64), nullable=False)
    # The entity a "..._of_b" direction acts on. The pair is stored in id order,
    # which says nothing about which compound the source described as affected, so
    # "b" alone is meaningless once stored. Null for directions that name no side.
    affected_entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True
    )
    severity: Mapped[Severity] = mapped_column(Enum(Severity), nullable=False)
    evidence_grade: Mapped[EvidenceGrade] = mapped_column(Enum(EvidenceGrade), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[InteractionStatus] = mapped_column(
        Enum(InteractionStatus), nullable=False, default=InteractionStatus.PENDING_REVIEW
    )
    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Review audit trail. Who accepted or rejected the claim, when, and why. Null
    # on rows no one has reviewed, including minor edges auto-published by the gate.
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="interaction", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("entity_a_id", "entity_b_id", name="uq_interaction_pair"),
        Index("ix_interaction_a", "entity_a_id"),
        Index("ix_interaction_b", "entity_b_id"),
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    interaction_id: Mapped[int] = mapped_column(ForeignKey("interactions.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    span: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    interaction: Mapped[Interaction] = relationship(back_populates="evidence")


class UpperLimit(Base):
    """Tolerable upper intake level for a nutrient, per NIH ODS."""

    __tablename__ = "upper_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    population: Mapped[str] = mapped_column(String(64), nullable=False, default="adult")
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    __table_args__ = (
        UniqueConstraint("entity_id", "population", name="uq_ul_entity_population"),
    )


class TimingRule(Base):
    """Separation requirement between two entities."""

    __tablename__ = "timing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_a_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    entity_b_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    separation_hours: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    __table_args__ = (
        UniqueConstraint("entity_a_id", "entity_b_id", name="uq_timing_pair"),
    )


class QuarantinedTriple(Base):
    """A candidate triple that failed verification or resolution. Never silently dropped."""

    __tablename__ = "quarantined_triples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConflictRecord(Base):
    """Two sources disagree about the same pair. Surfaced, never averaged away."""

    __tablename__ = "conflict_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    interaction_id: Mapped[int] = mapped_column(ForeignKey("interactions.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    existing_value: Mapped[str] = mapped_column(String(255), nullable=False)
    incoming_value: Mapped[str] = mapped_column(String(255), nullable=False)
    incoming_source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

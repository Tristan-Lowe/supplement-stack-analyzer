"""Pydantic schema the extraction model must satisfy.

The span field is what makes this pipeline auditable: every claim must quote the
source text it came from, and that quote is verified programmatically before the
triple is stored.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ssa.models import EvidenceGrade, Severity

Direction = Literal[
    "decreases_effect_of_b",
    "increases_effect_of_b",
    "decreases_absorption_of_b",
    "increases_toxicity_risk",
    "additive_effect",
    "unclear",
]


class CandidateTriple(BaseModel):
    """One extracted interaction claim, not yet verified or stored."""

    compound_a: str = Field(min_length=1, description="First compound, as named in the source")
    compound_b: str = Field(min_length=1, description="Second compound, as named in the source")
    mechanism: str = Field(
        min_length=1, description="Why the interaction occurs, one or two sentences"
    )
    direction: Direction
    severity: Severity
    evidence_grade: EvidenceGrade
    span: str = Field(
        min_length=1, description="Verbatim quote from the source supporting this claim"
    )

    @field_validator("span")
    @classmethod
    def span_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("span must contain non-whitespace text")
        return value

    @model_validator(mode="after")
    def compounds_must_differ(self) -> CandidateTriple:
        if self.compound_a.strip().lower() == self.compound_b.strip().lower():
            raise ValueError("compound_a and compound_b must be different compounds")
        return self


class ExtractionResult(BaseModel):
    """Top-level structured output returned by the extraction model."""

    triples: list[CandidateTriple] = Field(
        default_factory=list,
        description="Every interaction claim supported by the source text. Empty if none.",
    )

"""Resolution pipeline: raw text to a registry entity, an ambiguity, or nothing.

The resolver never guesses. Ambiguity is surfaced to the caller so the product
can ask the user, and an unmatched compound is reported as unknown rather than
silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from ssa.normalize import normalize_name, strip_salt_forms
from ssa.registry import all_normalized_aliases, find_by_alias

# Below this rapidfuzz ratio a fuzzy candidate is discarded. Chosen so that
# "ashwaganda"/"ashwagandha" (95.2) matches while "manganese"/"magnesium" (66.7)
# does not — near-miss mineral names are the dangerous false-positive class.
FUZZY_THRESHOLD = 88

# A fuzzy match must beat the runner-up by this margin, otherwise it is ambiguous.
FUZZY_MARGIN = 5

# Inputs this short or this generic are never resolved.
VAGUE_TERMS: frozenset[str] = frozenset(
    {
        "vitamin",
        "vitamin b",
        "vitamin d",
        "mineral",
        "multivitamin",
        "supplement",
        "protein",
    }
)


@dataclass(frozen=True)
class Resolved:
    entity_id: int
    matched_via: str  # "alias" | "salt_stripped" | "fuzzy"
    score: float = 100.0


@dataclass(frozen=True)
class Ambiguous:
    raw: str
    candidate_ids: list[int]


@dataclass(frozen=True)
class Unknown:
    raw: str


Resolution = Resolved | Ambiguous | Unknown


def resolve(session: Session, raw_name: str) -> Resolution:
    """Resolve raw text to an entity through four ordered stages."""
    normalized = normalize_name(raw_name)

    if normalized in VAGUE_TERMS:
        return Unknown(raw=raw_name)

    # Stage 1 — exact alias match.
    matches = find_by_alias(session, raw_name)
    if len(matches) == 1:
        return Resolved(entity_id=matches[0].id, matched_via="alias")
    if len(matches) > 1:
        return Ambiguous(raw=raw_name, candidate_ids=[e.id for e in matches])

    # Stage 2 — strip salt and chelate forms, then retry exact match.
    stripped = strip_salt_forms(normalized)
    if stripped != normalized:
        matches = find_by_alias(session, stripped)
        if len(matches) == 1:
            return Resolved(entity_id=matches[0].id, matched_via="salt_stripped")
        if len(matches) > 1:
            return Ambiguous(raw=raw_name, candidate_ids=[e.id for e in matches])

    # Stage 3 — fuzzy match against every known alias.
    candidates = all_normalized_aliases(session)
    if not candidates:
        return Unknown(raw=raw_name)

    choices = [alias for alias, _ in candidates]
    scored = process.extract(normalized, choices, scorer=fuzz.ratio, limit=5)
    above = [(alias, score) for alias, score, _ in scored if score >= FUZZY_THRESHOLD]
    if not above:
        return Unknown(raw=raw_name)

    alias_to_entity = dict(candidates)
    best_alias, best_score = above[0]
    best_entity_id = alias_to_entity[best_alias]

    distinct_ids = {alias_to_entity[a] for a, _ in above}
    if len(distinct_ids) > 1:
        runner_up = above[1][1]
        if best_score - runner_up < FUZZY_MARGIN:
            return Ambiguous(raw=raw_name, candidate_ids=sorted(distinct_ids))

    return Resolved(
        entity_id=best_entity_id, matched_via="fuzzy", score=float(best_score)
    )

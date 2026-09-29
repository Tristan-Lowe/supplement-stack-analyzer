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

# A fuzzy match must beat the runner-up ENTITY by this margin, else it is ambiguous.
FUZZY_MARGIN = 5

# How many alias candidates to score before grouping by entity. Must be generous:
# a popular entity can own many aliases, and a narrow window would let all of them
# crowd out a genuine near-tie with a different entity, silently defeating the
# ambiguity check below.
FUZZY_CANDIDATE_WINDOW = 50

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


def build_alias_index(session: Session) -> list[tuple[str, int]]:
    """Snapshot every (normalized_alias, entity_id) pair for batch resolution.

    The fuzzy stage otherwise re-reads the whole alias table on every call. That
    is invisible for one lookup and severe for many: resolving a few hundred names
    meant a few hundred full table scans, slow enough that a serverless database
    reclaimed the connection mid-run.

    Callers that resolve many names against an unchanging registry should build
    this once and pass it in. Callers that *mutate* the registry between lookups —
    ingestion, which bootstraps new entities — must not, or they will match against
    a stale snapshot.
    """
    return all_normalized_aliases(session)


def resolve(
    session: Session,
    raw_name: str,
    alias_index: list[tuple[str, int]] | None = None,
) -> Resolution:
    """Resolve raw text to an entity through four ordered stages.

    Pass `alias_index` from build_alias_index() when resolving many names against
    a registry that is not changing.
    """
    normalized = normalize_name(raw_name)

    if normalized in VAGUE_TERMS:
        return Unknown(raw=raw_name)

    # When an index is supplied, every stage is served from memory. Without it
    # each stage is a separate round trip, which on a remote database dominates
    # the cost of resolving a stack.
    def _lookup(key: str) -> list[int]:
        if alias_index is None:
            return [e.id for e in find_by_alias(session, key)]
        return sorted({eid for alias, eid in alias_index if alias == key})

    # Stage 1 — exact alias match.
    matches = _lookup(normalized)
    if len(matches) == 1:
        return Resolved(entity_id=matches[0], matched_via="alias")
    if len(matches) > 1:
        return Ambiguous(raw=raw_name, candidate_ids=matches)

    # Stage 2 — strip salt and chelate forms, then retry exact match.
    stripped = strip_salt_forms(normalized)
    if stripped != normalized:
        matches = _lookup(stripped)
        if len(matches) == 1:
            return Resolved(entity_id=matches[0], matched_via="salt_stripped")
        if len(matches) > 1:
            return Ambiguous(raw=raw_name, candidate_ids=matches)

    # Stage 3 — fuzzy match against every known alias.
    candidates = all_normalized_aliases(session) if alias_index is None else alias_index
    if not candidates:
        return Unknown(raw=raw_name)

    choices = [alias for alias, _ in candidates]
    scored = process.extract(
        normalized, choices, scorer=fuzz.ratio, limit=FUZZY_CANDIDATE_WINDOW
    )

    # Resolve each hit through its INDEX, not the alias string. Two entities can
    # share an alias ("potassium" as a nutrient and as a drug), and a string-keyed
    # lookup silently drops one of them — a guess, in the one component whose
    # contract is never to guess.
    best_by_entity: dict[int, float] = {}
    for _alias, score, index in scored:
        if score < FUZZY_THRESHOLD:
            continue
        entity_id = candidates[index][1]
        if score > best_by_entity.get(entity_id, 0.0):
            best_by_entity[entity_id] = score

    if not best_by_entity:
        return Unknown(raw=raw_name)

    # Compare entities, not aliases. Several aliases of one entity are not evidence
    # of a contest; two different entities scoring alike are.
    ranked = sorted(best_by_entity.items(), key=lambda item: item[1], reverse=True)
    best_entity_id, best_score = ranked[0]

    if len(ranked) > 1 and best_score - ranked[1][1] < FUZZY_MARGIN:
        return Ambiguous(raw=raw_name, candidate_ids=sorted(best_by_entity))

    return Resolved(
        entity_id=best_entity_id, matched_via="fuzzy", score=float(best_score)
    )

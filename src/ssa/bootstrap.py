"""Registry bootstrap: create entities from authoritative sources during ingestion.

The knowledge graph cannot populate itself. Extraction names compounds, but the
resolver only recognises what the registry already holds — so a fresh database
quarantines everything, including the drug the label is about.

This module closes that loop by deferring to RxNorm rather than inventing
entities from model output. That distinction is the whole point: creating
"levothyroxine" because the National Library of Medicine publishes an ingredient
concept for it is not a guess; creating it because a language model wrote the
word would be.

**Ingestion only.** This performs network I/O and must never run in the request
path, which is deliberately offline and deterministic.
"""

from __future__ import annotations

import logging
import re

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from ssa.connectors.rxnorm import lookup_ingredient
from ssa.models import Entity, EntityKind
from ssa.registry import add_alias, get_or_create_entity

logger = logging.getLogger(__name__)

# RxNorm answers almost any query with *something*. Requiring the returned
# ingredient to actually resemble what we asked for is what stops a class term
# being silently bound to one arbitrary member of that class.
#
# Measured separation on real label terms: every correct match scores 100
# (token_set handles "cholestyramine" -> "cholestyramine resin"), while
# "salicylates" -> "salicylic acid" scores 56, "glucocorticoids" ->
# "hydrocortisone" 48, and "proton pump inhibitors" -> "omeprazole" 25.
NAME_MATCH_THRESHOLD = 80

# A parenthetical introduced this way names an EXAMPLE of a class, not a synonym.
# "Tricyclic antidepressants (e.g., amitriptyline)" is a warning about the whole
# class; binding it to amitriptyline alone would silently narrow a clinical
# warning to one of its members.
_EXAMPLE_MARKER = re.compile(r"^\s*(e\.?g\.?|such as|including|eg)\b", re.IGNORECASE)

_PARENTHETICAL = re.compile(r"\(([^)]*)\)")


def name_variants(raw_name: str) -> list[str]:
    """Safe alternative spellings to try against RxNorm, in priority order.

    Deliberately conservative. Recovering a few more names is not worth binding a
    class-level warning to a single drug.
    """
    variants = [raw_name]

    outside = _PARENTHETICAL.sub("", raw_name).strip(" ,/;")
    if outside and outside != raw_name:
        variants.append(outside)

    for inner in _PARENTHETICAL.findall(raw_name):
        inner = inner.strip()
        if not inner or _EXAMPLE_MARKER.match(inner):
            continue
        variants.append(inner)

    return variants


def bootstrap_entity(session: Session, raw_name: str) -> Entity | None:
    """Create a registry entity for `raw_name` from RxNorm, or return None.

    Returns None rather than binding a name RxNorm did not really recognise. An
    unresolved compound is a visible gap; a wrongly resolved one is a false claim
    about somebody's medication.

    The surface form is recorded as an alias, so the same wording resolves without
    a network call next time — every bootstrap makes the offline resolver
    strictly better.
    """
    for variant in name_variants(raw_name):
        concept = lookup_ingredient(variant)
        if concept is None:
            continue

        score = fuzz.token_set_ratio(variant.lower(), concept.name.lower())
        if score < NAME_MATCH_THRESHOLD:
            logger.info(
                "Refusing bootstrap %r -> %r (similarity %.0f < %d); likely a drug "
                "class rather than an ingredient",
                variant,
                concept.name,
                score,
                NAME_MATCH_THRESHOLD,
            )
            continue

        canonical = concept.name.strip().title()
        entity = get_or_create_entity(
            session, EntityKind.DRUG, canonical, rxcui=concept.rxcui
        )
        add_alias(session, entity, raw_name, source="rxnorm")
        session.commit()
        logger.info(
            "Bootstrapped %r -> %s (rxcui %s)", raw_name, canonical, concept.rxcui
        )
        return entity

    return None

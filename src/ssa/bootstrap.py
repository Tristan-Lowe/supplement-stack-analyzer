"""Registry bootstrap: create entities from authoritative sources during ingestion.

The knowledge graph cannot populate itself. Extraction names compounds, but the
resolver only recognises what the registry already holds — so a fresh database
quarantines everything, including the drug the label is about.

This module closes that loop by deferring to RxNorm rather than inventing
entities from model output. That distinction is the whole point: creating
"levothyroxine" because the National Library of Medicine has an ingredient
concept for it is not a guess; creating it because a language model wrote the
word would be.

**Ingestion only.** This performs network I/O and must never run in the request
path, which is deliberately offline and deterministic.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ssa.connectors.rxnorm import lookup_ingredient
from ssa.models import Entity, EntityKind
from ssa.registry import add_alias, get_or_create_entity

logger = logging.getLogger(__name__)


def bootstrap_entity(session: Session, raw_name: str) -> Entity | None:
    """Create a registry entity for `raw_name` from RxNorm, or return None.

    The surface form is recorded as an alias so the same wording resolves without
    a network call next time — every bootstrap makes the offline resolver
    strictly better.
    """
    concept = lookup_ingredient(raw_name)
    if concept is None:
        return None

    canonical = concept.name.strip().title()
    entity = get_or_create_entity(
        session, EntityKind.DRUG, canonical, rxcui=concept.rxcui
    )
    add_alias(session, entity, raw_name, source="rxnorm")
    session.commit()
    logger.info("Bootstrapped %r -> %s (rxcui %s)", raw_name, canonical, concept.rxcui)
    return entity

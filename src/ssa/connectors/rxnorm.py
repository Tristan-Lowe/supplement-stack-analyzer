"""RxNorm name normalization. Fetch only — never writes to the database.

Note: NLM discontinued the RxNav Drug Interaction API in January 2024. The
normalization endpoints used here are unaffected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
TIMEOUT_SECONDS = 15

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrugConcept:
    rxcui: str
    name: str


def lookup_drug(name: str) -> DrugConcept | None:
    """Resolve a drug or brand name to an RxCUI and its RxNorm preferred name.

    Returns None when the name is unknown or the service is unavailable —
    callers must treat that as "not identified", never as "no interactions".
    """
    try:
        response = requests.get(
            f"{RXNORM_BASE}/rxcui.json",
            params={"name": name, "search": "2"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("RxNorm lookup failed for %r: %s", name, exc)
        return None

    try:
        ids = response.json().get("idGroup", {}).get("rxnormId", [])
    except (ValueError, AttributeError) as exc:
        logger.warning("RxNorm returned unparseable body for %r: %s", name, exc)
        return None
    if not ids:
        return None
    rxcui = ids[0]

    try:
        prop = requests.get(
            f"{RXNORM_BASE}/rxcui/{rxcui}/property.json",
            params={"propName": "RxNorm Name"},
            timeout=TIMEOUT_SECONDS,
        )
        prop.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("RxNorm property fetch failed for %s: %s", rxcui, exc)
        return DrugConcept(rxcui=rxcui, name=name)

    try:
        concepts = prop.json().get("propConceptGroup", {}).get("propConcept", [])
        preferred = next(
            (c["propValue"] for c in concepts if c.get("propName") == "RxNorm Name"),
            name,
        )
    except (ValueError, AttributeError, KeyError, TypeError) as exc:
        logger.warning("RxNorm property body unusable for %s: %s", rxcui, exc)
        preferred = name
    return DrugConcept(rxcui=rxcui, name=preferred)


def lookup_ingredient(name: str) -> DrugConcept | None:
    """Resolve a name to its RxNorm *ingredient*, collapsing dose forms and brands.

    This is the function the registry should use, not lookup_drug. RxNorm assigns
    distinct RxCUIs to "levothyroxine" (10582), "Synthroid" (224920), and
    "levothyroxine sodium Oral Tablet" (2649207). Creating an entity per RxCUI
    would fragment one drug into three, and interactions would scatter across
    them. Walking to the ingredient collapses all three to 10582.

    Returns None when the name is unknown or the service is unavailable — callers
    must treat that as "not identified", never as "no interactions".
    """
    concept = lookup_drug(name)
    if concept is None:
        return None

    try:
        response = requests.get(
            f"{RXNORM_BASE}/rxcui/{concept.rxcui}/related.json",
            params={"tty": "IN"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        groups = response.json().get("relatedGroup", {}).get("conceptGroup", []) or []
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.warning("RxNorm ingredient lookup failed for %s: %s", concept.rxcui, exc)
        return concept

    for group in groups:
        for prop in group.get("conceptProperties") or []:
            return DrugConcept(rxcui=prop["rxcui"], name=prop["name"])

    # Already an ingredient, or no ingredient relationship exists.
    return concept



@dataclass(frozen=True)
class RelatedConcept:
    rxcui: str
    name: str
    tty: str


def related_concepts(rxcui: str, ttys: tuple[str, ...]) -> list[RelatedConcept]:
    """Concepts of the given term types related to `rxcui`. Empty on any failure."""
    try:
        response = requests.get(
            f"{RXNORM_BASE}/rxcui/{rxcui}/related.json",
            params={"tty": " ".join(ttys)},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        groups = response.json().get("relatedGroup", {}).get("conceptGroup", []) or []
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.warning("RxNorm related lookup failed for %s: %s", rxcui, exc)
        return []

    out: list[RelatedConcept] = []
    for group in groups:
        for prop in group.get("conceptProperties") or []:
            out.append(
                RelatedConcept(rxcui=prop["rxcui"], name=prop["name"], tty=prop["tty"])
            )
    return out


def ingredient_ids(rxcui: str) -> set[str] | None:
    """RxCUIs of every ingredient in a concept, or None if the lookup failed.

    None and an empty set mean different things: None is "could not tell", which
    callers must treat as a refusal, never as "single ingredient".
    """
    try:
        response = requests.get(
            f"{RXNORM_BASE}/rxcui/{rxcui}/related.json",
            params={"tty": "IN"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        groups = response.json().get("relatedGroup", {}).get("conceptGroup", []) or []
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.warning("RxNorm ingredient lookup failed for %s: %s", rxcui, exc)
        return None

    return {
        prop["rxcui"]
        for group in groups
        for prop in (group.get("conceptProperties") or [])
    }

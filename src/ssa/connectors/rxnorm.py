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

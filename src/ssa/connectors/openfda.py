"""openFDA structured product label connector.

Pulls the free-text "Drug Interactions" section of a label. That text is the
input to the extraction pipeline; nothing here interprets it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

OPENFDA_BASE = "https://api.fda.gov"
LABEL_URL_TEMPLATE = "https://api.fda.gov/drug/label.json?search=id:{label_id}"
TIMEOUT_SECONDS = 20

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrugLabelSection:
    label_id: str
    generic_name: str
    text: str
    source_url: str


def fetch_interaction_sections(drug_name: str, limit: int = 5) -> list[DrugLabelSection]:
    """Fetch drug-interaction label sections for a drug name.

    Returns an empty list when nothing is found or the service errors. Callers
    must treat an empty list as "no data retrieved", never as "no interactions".
    """
    try:
        response = requests.get(
            f"{OPENFDA_BASE}/drug/label.json",
            params={"search": f'openfda.generic_name:"{drug_name}"', "limit": limit},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("openFDA fetch failed for %r: %s", drug_name, exc)
        return []

    sections: list[DrugLabelSection] = []
    for result in response.json().get("results", []):
        paragraphs = result.get("drug_interactions") or []
        if not paragraphs:
            continue
        label_id = result.get("id", "")
        generic_names = result.get("openfda", {}).get("generic_name", [])
        sections.append(
            DrugLabelSection(
                label_id=label_id,
                generic_name=generic_names[0] if generic_names else drug_name,
                text="\n\n".join(paragraphs),
                source_url=LABEL_URL_TEMPLATE.format(label_id=label_id),
            )
        )
    return sections

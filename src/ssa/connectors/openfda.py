"""openFDA structured product label connector.

Pulls the free-text "Drug Interactions" section of a label. That text is the
input to the extraction pipeline; nothing here interprets it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

import requests

OPENFDA_BASE = "https://api.fda.gov"
LABEL_URL_TEMPLATE = "https://api.fda.gov/drug/label.json?search=id:{label_id}"
NAME_URL_TEMPLATE = "https://api.fda.gov/drug/label.json?search=openfda.generic_name:{name}"
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

    try:
        results = response.json().get("results", [])
    except (ValueError, AttributeError) as exc:
        logger.warning("openFDA returned unparseable body for %r: %s", drug_name, exc)
        return []

    sections: list[DrugLabelSection] = []
    for result in results:
        paragraphs = result.get("drug_interactions") or []
        if not paragraphs:
            continue
        label_id = result.get("id", "")
        generic_names = result.get("openfda", {}).get("generic_name", [])
        resolved_name = generic_names[0] if generic_names else drug_name

        # These URLs are shown to users as citations. An unescaped id, or a result
        # with no id at all, produces a visibly broken link — sloppiness on exactly
        # the element meant to establish trust.
        if label_id:
            source_url = LABEL_URL_TEMPLATE.format(label_id=quote(label_id, safe=""))
        else:
            source_url = NAME_URL_TEMPLATE.format(
                name=quote(f'"{resolved_name}"', safe="")
            )

        sections.append(
            DrugLabelSection(
                label_id=label_id,
                generic_name=resolved_name,
                text="\n\n".join(paragraphs),
                source_url=source_url,
            )
        )
    return sections

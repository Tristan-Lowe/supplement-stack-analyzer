"""NIH Dietary Supplement Label Database connector.

Expands a branded product into its constituent ingredients with amounts.
Fetch only — never writes to the database.
API guide: https://dsld.od.nih.gov/api-guide
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

DSLD_BASE = "https://api.ods.od.nih.gov/dsld/v9"
TIMEOUT_SECONDS = 20

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LabelIngredient:
    name: str
    amount: float
    unit: str


@dataclass
class SupplementLabel:
    dsld_id: str
    full_name: str
    brand: str
    ingredients: list[LabelIngredient] = field(default_factory=list)
    unquantified: list[str] = field(default_factory=list)


def search_labels(query: str, limit: int = 10) -> list[tuple[str, str]]:
    """Search DSLD for products matching a name. Returns (dsld_id, full_name) pairs."""
    try:
        response = requests.get(
            f"{DSLD_BASE}/search-filter",
            params={"q": query, "size": limit},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("DSLD search failed for %r: %s", query, exc)
        return []

    try:
        hits = response.json().get("hits", [])
    except (ValueError, AttributeError) as exc:
        logger.warning("DSLD search returned unparseable body for %r: %s", query, exc)
        return []

    results: list[tuple[str, str]] = []
    for hit in hits:
        dsld_id = (hit or {}).get("_id")
        if not dsld_id:
            logger.warning("DSLD search hit without _id, skipped: %r", hit)
            continue
        source = (hit.get("_source") or {})
        results.append((dsld_id, source.get("fullName", "")))
    return results


def fetch_label(dsld_id: str) -> SupplementLabel | None:
    """Fetch a single label and expand it into quantified ingredients.

    Ingredients without a stated quantity (proprietary blends) are recorded
    separately in `unquantified` rather than dropped — the analysis engine
    must be able to tell the user what it could not measure.
    """
    try:
        response = requests.get(f"{DSLD_BASE}/label/{dsld_id}", timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("DSLD label fetch failed for %s: %s", dsld_id, exc)
        return None

    try:
        payload = response.json()
    except (ValueError, AttributeError) as exc:
        logger.warning("DSLD label %s returned unparseable body: %s", dsld_id, exc)
        return None

    label = SupplementLabel(
        dsld_id=dsld_id,
        full_name=payload.get("fullName", ""),
        brand=payload.get("brandName", ""),
    )

    for row in payload.get("ingredientRows", []):
        name = row.get("name", "").strip()
        if not name:
            continue
        quantities = row.get("quantity") or []
        if not quantities:
            label.unquantified.append(name)
            continue

        # A malformed quantity ("trace", a missing key, a null) must not crash the
        # whole label. Record it as unmeasured so the analysis engine can tell the
        # user what it could not check, rather than silently omitting it.
        try:
            first = quantities[0]
            amount = float(first["quantity"])
            unit = first["unit"]
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            logger.warning("DSLD label %s: unusable quantity for %r (%s)", dsld_id, name, exc)
            label.unquantified.append(name)
            continue

        label.ingredients.append(LabelIngredient(name=name, amount=amount, unit=unit))

    return label

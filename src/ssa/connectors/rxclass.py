"""RxClass (NLM) drug-class membership. Fetch only — never writes to the database."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

RXCLASS_BASE = "https://rxnav.nlm.nih.gov/REST/rxclass"
TIMEOUT_SECONDS = 20

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassMember:
    rxcui: str
    name: str


def class_url(class_id: str, rela_source: str = "ATC") -> str:
    """Human-checkable URL for a class's member list, used as the citation."""
    return f"{RXCLASS_BASE}/classMembers.json?classId={class_id}&relaSource={rela_source}"


def class_members(class_id: str, rela_source: str = "ATC") -> list[ClassMember] | None:
    """Single-ingredient members of a class, or None if the lookup failed.

    Combination products ("aluminum hydroxide / magnesium carbonate") are
    excluded: membership of a combination says nothing reliable about either
    ingredient alone. None and [] differ — None means "could not tell".
    """
    try:
        response = requests.get(
            f"{RXCLASS_BASE}/classMembers.json",
            params={"classId": class_id, "relaSource": rela_source},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        group = response.json().get("drugMemberGroup") or {}
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.warning("RxClass lookup failed for %s: %s", class_id, exc)
        return None

    members: dict[str, ClassMember] = {}
    for item in group.get("drugMember") or []:
        concept = item.get("minConcept") or {}
        rxcui, name = concept.get("rxcui"), (concept.get("name") or "").strip()
        if not rxcui or not name or " / " in name:
            continue
        members.setdefault(rxcui, ClassMember(rxcui=rxcui, name=name))
    return list(members.values())

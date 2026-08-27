"""Pure string normalization for entity matching. No I/O, no database."""

from __future__ import annotations

import re
import unicodedata

# Surface-form abbreviations seen on real supplement labels and in user input.
#
# Two deliberate absences:
#   "mg" is NOT a key. It is the dose unit on nearly every label, and mapping it to
#   magnesium would corrupt every dose string that passes through here.
#   "ala" is NOT a key. It means alpha-LIPOIC acid or alpha-LINOLENIC acid depending
#   on context. Expanding it to either one would be a guess, and the resolver's
#   contract is that ambiguity surfaces as Unknown rather than being guessed at.
ABBREVIATIONS: dict[str, str] = {
    "mag": "magnesium",
    "vit": "vitamin",
    "vits": "vitamin",
    "ca": "calcium",
    "zn": "zinc",
    "fe": "iron",
    "k2": "vitamin k2",
    "d3": "d3",
    "coq10": "coenzyme q10",
    "nac": "n acetylcysteine",
    "epa": "eicosapentaenoic acid",
    "dha": "docosahexaenoic acid",
}

# Salt, chelate, and ester forms that do not change the active element.
SALT_FORMS: frozenset[str] = frozenset(
    {
        "bisglycinate",
        "glycinate",
        "citrate",
        "oxide",
        "malate",
        "threonate",
        "taurate",
        "orotate",
        "chloride",
        "sulfate",
        "gluconate",
        "picolinate",
        "carbonate",
        "aspartate",
        "fumarate",
        "chelate",
        "chelated",
        "monohydrate",
    }
)

_PUNCT = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Normalize a compound name to a stable matching key.

    Lowercases, folds unicode, strips punctuation, collapses whitespace,
    and expands known abbreviations.
    """
    folded = unicodedata.normalize("NFKD", raw)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    lowered = folded.lower()
    spaced = _PUNCT.sub(" ", lowered)
    collapsed = _WS.sub(" ", spaced).strip()

    tokens = [ABBREVIATIONS.get(token, token) for token in collapsed.split(" ")]
    return " ".join(tokens)


def strip_salt_forms(normalized: str) -> str:
    """Reduce a normalized name to its active element by dropping salt/chelate words.

    Only strips when at least one non-salt token remains, so "citrate" alone
    is left intact rather than reduced to an empty string.
    """
    tokens = normalized.split(" ")
    kept = [t for t in tokens if t not in SALT_FORMS]
    if not kept:
        return normalized
    return " ".join(kept)

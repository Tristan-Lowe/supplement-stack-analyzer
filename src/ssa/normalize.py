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
    "hcl": "hydrochloride",
    # "creatine mono" is how people write creatine monohydrate. Expanding it lets
    # the salt stage strip it like any other form.
    "mono": "monohydrate",
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
        "hydrochloride",
    }
)

# Preparation and dose-form words that describe how a compound is sold, not what
# it is. An extract or root of an herb carries that herb's interactions, and a
# capsule of sertraline is sertraline.
#
# "oil" and "seed" are deliberately absent: "fish oil" is not fish, and "grape
# seed extract" is not grapes.
PREPARATION_FORMS: frozenset[str] = frozenset(
    {
        "extract",
        "root",
        "husk",
        "standardized",
        "preparation",
        "powder",
        "leaf",
        "flower",
        "herb",
        "berry",
        "berries",
        "concentrate",
        "supercritical",
        # Dose forms and packaging say how a compound is taken, not what it is.
        "tablet",
        "tablets",
        "capsule",
        "capsules",
        "caplet",
        "caplets",
        "softgel",
        "softgels",
        "chewable",
        "supplement",
        "supplements",
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

    expanded = " ".join(ABBREVIATIONS.get(token, token) for token in collapsed.split(" "))

    # An expansion can repeat the word it follows: "vitamin k2" expands k2 to
    # "vitamin k2" and would otherwise produce "vitamin vitamin k2", a key that
    # matches nothing. Collapse adjacent repeats.
    deduped: list[str] = []
    for token in expanded.split(" "):
        if not deduped or deduped[-1] != token:
            deduped.append(token)
    return " ".join(deduped)


# Stereochemistry prefixes. Ubiquitous on labels: L-theanine, L-carnitine,
# D-aspartic acid, magnesium L-threonate, acetyl-L-carnitine.
STEREO_MARKERS: frozenset[str] = frozenset({"l", "d", "dl", "ld"})


def strip_salt_forms(normalized: str) -> str:
    """Reduce a normalized name to its active element.

    Drops salt and chelate words, preparation words, and stereochemistry prefixes.

    A stereo marker is only dropped when another token follows it. That guard is
    load-bearing: "vitamin d" would otherwise reduce to "vitamin", silently
    turning a real compound into a term the resolver treats as too vague to
    resolve. "magnesium l threonate" -> "magnesium" is the case we want.

    Only strips when at least one token remains, so "citrate" alone is left
    intact rather than reduced to an empty string.
    """
    tokens = normalized.split(" ")

    without_stereo: list[str] = []
    for position, token in enumerate(tokens):
        is_last = position == len(tokens) - 1
        if token in STEREO_MARKERS and not is_last:
            continue
        without_stereo.append(token)

    kept = [
        t for t in without_stereo if t not in SALT_FORMS and t not in PREPARATION_FORMS
    ]
    if not kept:
        return normalized
    return " ".join(kept)

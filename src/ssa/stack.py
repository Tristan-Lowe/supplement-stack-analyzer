"""Stack items and a deterministic text parser.

The LLM-backed parser that handles genuinely messy input is plan two. This one
handles the common "name amount unit" shape so the analysis engine can be
exercised end to end with no network dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNITS = ("mcg", "mg", "iu", "g", "ml")

_ITEM = re.compile(
    r"^(?P<name>.*?)\s*"
    r"(?:(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>mcg|mg|iu|g|ml))?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StackItem:
    raw: str
    amount: float | None
    unit: str | None


def parse_stack_text(text: str) -> list[StackItem]:
    """Parse newline- or comma-separated stack text into StackItems.

    An item with no recognizable dose keeps amount and unit as None rather than
    being guessed at — the upper-limit check simply skips it and says so.
    """
    fragments: list[str] = []
    for line in text.splitlines():
        fragments.extend(part for part in line.split(","))

    items: list[StackItem] = []
    for fragment in fragments:
        cleaned = fragment.strip()
        if not cleaned:
            continue
        match = _ITEM.match(cleaned)
        if match is None or not match.group("name").strip():
            items.append(StackItem(raw=cleaned, amount=None, unit=None))
            continue
        amount = match.group("amount")
        unit = match.group("unit")
        items.append(
            StackItem(
                raw=match.group("name").strip(),
                amount=float(amount) if amount else None,
                unit=unit.lower() if unit else None,
            )
        )
    return items

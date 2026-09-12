"""Refuse replay conditions built from one run's data.

A discovery run sees one member, one balance, one date. A condition built from those
passes on the recorded input and fails on every other, while still satisfying the schema —
so the check has to live here rather than in validation alone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

MIN_LITERAL_LENGTH = 3
_MULTI_DIGIT = re.compile(r"\d{2,}")

_ADVICE = (
    "Replay conditions must hold for every input. Use static screen text such as a heading, "
    "label or column name instead."
)


def overfit_reason(text: str, literals: Sequence[str]) -> str | None:
    """Why `text` must not become a replay condition, or None when it is safe."""
    lowered = text.lower()
    for literal in literals:
        if len(literal) >= MIN_LITERAL_LENGTH and literal.lower() in lowered:
            return f"{text!r} contains {literal!r}, a value from this run. {_ADVICE}"
    if match := _MULTI_DIGIT.search(text):
        return f"{text!r} contains the number {match.group()!r}, which varies per input. {_ADVICE}"
    return None

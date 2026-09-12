"""Refuse replay conditions built from one run's data.

A discovery run sees one member, one balance, one date. A condition built from those
passes on the recorded input and fails on every other, while still satisfying the schema —
so the check has to live here rather than in validation alone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

MIN_LITERAL_LENGTH = 3
# An identifier long enough to be a record key, or an amount with cents. Short runs are left
# alone: the target's own share codes are S01 and S09, and "Page 10 of 12" is a static label —
# rejecting those would refuse the only stable heading a screen has.
IDENTIFIER_DIGITS = 5
_RUN_SPECIFIC_NUMBER = re.compile(rf"\d[\d,]*\.\d{{2}}|\d{{{IDENTIFIER_DIGITS},}}")

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
    if match := _RUN_SPECIFIC_NUMBER.search(text):
        return (
            f"{text!r} contains {match.group()!r}, which reads as an amount or a record "
            f"identifier and so varies per input. {_ADVICE}"
        )
    return None

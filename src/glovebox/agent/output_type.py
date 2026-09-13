"""Correct an output's declared type from the value the run actually saw.

The model picks the type when it records an extraction, and it picks `string` by default. A
balance returned as "$1250.75" is a weaker contract than one returned as 1250.75: every caller
has to strip the symbol and parse it, and the artifact stops saying what the value *is*.

Only a defaulted `string` is second-guessed, and only when the value plainly reads as money —
a currency symbol, thousands separators, or a two-decimal fraction. A bare run of digits is
left alone on purpose: a member number is an identifier, not a quantity, and typing it numeric
would drop leading zeros and imply arithmetic on it makes sense.
"""

from __future__ import annotations

import re

#: Money as these screens render it: an optional sign or bracket, an optional currency symbol,
#: digits with optional thousands separators, and either a decimal fraction or a separator —
#: one of which must be present, which is what keeps identifiers out.
_AMOUNT = re.compile(
    r"""^\(?\s*[-+]?\s*[$£€¥]?\s*
        (?:\d{1,3}(?:,\d{3})+(?:\.\d+)?   # 18,930.00  or  18,930
         |\d+\.\d{1,4})                    # 1250.75
        \s*\)?$""",
    re.VERBOSE,
)
_CURRENCY_PREFIXED = re.compile(r"^\(?\s*[-+]?\s*[$£€¥]\s*\d")


def inferred_output_type(declared: str, observed: str | None) -> str:
    """The type this output should carry, given what the run read off the screen."""
    if declared != "string" or not observed:
        return declared
    value = observed.strip()
    if _AMOUNT.match(value) or _CURRENCY_PREFIXED.match(value):
        return "number"
    return declared

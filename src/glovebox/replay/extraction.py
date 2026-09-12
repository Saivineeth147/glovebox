"""Turn the text under a recorded target into the output value the step promised."""

from __future__ import annotations

import re


def extracted_value(text: str, regex: str | None) -> str | None:
    """The promised value, or None when the recorded shape is absent from `text`.

    A recorded regex is an assertion about what the value looks like. Falling back to the
    raw text when it does not match reports whatever happens to be on screen as a result —
    a member number in place of a savings balance — and the caller cannot tell.
    """
    if not regex:
        return text
    match = re.search(regex, text)
    if match is None:
        return None
    return match.group(1) if match.groups() else match.group(0)

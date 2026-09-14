"""One definition of "that text is on the screen", shared by the recorder and every surface.

The recorder marks an outcome `verified` when its detector was seen during the run; replay
decides whether the same detector fires. If the two normalise differently the flag stops meaning
anything — and it fails in the direction that hurts: a legacy page rendering one sentence across
two table cells verifies at record time and never matches at replay, so the capability reports a
hard failure exactly where it promised a business outcome.
"""

from __future__ import annotations


def collapse_whitespace(text: str) -> str:
    """Lowercase and reduce every run of whitespace to a single space."""
    return " ".join(text.lower().split())


def contains_text(needle: str, haystack: str) -> bool:
    """Whether `needle` appears in `haystack`, ignoring case and how the page wrapped it."""
    return collapse_whitespace(needle) in collapse_whitespace(haystack)

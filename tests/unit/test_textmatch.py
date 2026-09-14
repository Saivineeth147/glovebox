"""`verified` is only worth recording if replay agrees with the recorder about what it saw."""

from __future__ import annotations

from glovebox.textmatch import collapse_whitespace, contains_text

# A legacy page renders one sentence across two table cells; the browser reports the break.
SPLIT_ACROSS_CELLS = "No member record\n   matched number 999999."


def test_should_find_text_the_page_wrapped_across_cells() -> None:
    assert contains_text("No member record matched", SPLIT_ACROSS_CELLS)


def test_should_ignore_case() -> None:
    assert contains_text("NO MEMBER RECORD MATCHED", SPLIT_ACROSS_CELLS)


def test_should_not_find_text_that_is_absent() -> None:
    assert not contains_text("Access denied", SPLIT_ACROSS_CELLS)


def test_should_collapse_every_run_of_whitespace_to_one_space() -> None:
    assert collapse_whitespace("  A\t\tB\n\nC  ") == "a b c"

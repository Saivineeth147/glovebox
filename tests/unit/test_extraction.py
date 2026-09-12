"""A recorded regex asserts the value's shape; replay must not report a mismatch as success."""

from __future__ import annotations

from glovebox.replay.extraction import extracted_value


def test_should_return_the_text_unchanged_when_no_regex_was_recorded() -> None:
    assert extracted_value("1,250.75", None) == "1,250.75"


def test_should_return_the_first_capture_group_when_the_regex_has_one() -> None:
    assert extracted_value("S01 Regular Savings $1250.75", r"\$([\d,.]+)") == "1250.75"


def test_should_return_the_whole_match_when_the_regex_has_no_group() -> None:
    assert extracted_value("balance 1250.75 USD", r"[\d.]+") == "1250.75"


def test_should_return_none_when_the_recorded_shape_is_absent() -> None:
    """The failed capability read a member number where a balance was promised."""
    assert extracted_value("100234", r"S01 Regular Savings \$([\d,.]+)") is None

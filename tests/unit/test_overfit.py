"""A discovery run sees one member and one balance; its conditions must not encode them."""

from __future__ import annotations

from glovebox.agent.overfit import overfit_reason


def test_should_reject_text_containing_a_record_time_parameter_value() -> None:
    reason = overfit_reason("Member No. 100234", ["100234"])
    assert reason is not None and "100234" in reason


def test_should_reject_text_containing_a_multi_digit_literal() -> None:
    """The failed run's balance reached no parameter and no extraction, only the screen."""
    assert overfit_reason("$1250.75", []) is not None


def test_should_accept_a_static_label() -> None:
    assert overfit_reason("Regular Savings", ["100234"]) is None


def test_should_accept_a_single_digit_because_it_is_usually_part_of_a_label() -> None:
    assert overfit_reason("Page 1", []) is None


def test_should_ignore_short_literals_so_one_character_input_cannot_reject_everything() -> None:
    assert overfit_reason("Share Accounts", ["a"]) is None

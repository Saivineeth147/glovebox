"""A discovery run sees one member and one balance; its conditions must not encode them."""

from __future__ import annotations

from glovebox.agent.overfit import overfit_reason
from glovebox.agent.recorder import Recorder
from glovebox.schema.capability import Parameter, ParamType


def _recorder(**kw) -> Recorder:
    return Recorder(
        capability_id="c",
        app_id="a",
        tenant=None,
        entry_url="http://127.0.0.1:8089/t/alpha/",
        params=[Parameter(name="member_id", type=ParamType.STRING, description="d")],
        model_name="test",
        run_id="r",
        **kw,
    )


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


def test_should_reject_a_condition_built_from_a_parameter_value_it_was_given() -> None:
    rec = _recorder(param_values={"member_id": "100234"})
    assert rec.overfit_reason("Member No. 100234") is not None


def test_should_reject_a_condition_built_from_a_value_read_off_the_screen() -> None:
    rec = _recorder()
    rec.note_observed_value("Doe, Jane")
    assert rec.overfit_reason("Name Doe, Jane") is not None


def test_should_accept_a_static_label_when_values_are_known() -> None:
    rec = _recorder(param_values={"member_id": "100234"})
    assert rec.overfit_reason("Share Accounts") is None

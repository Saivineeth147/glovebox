"""A discovery run sees one member and one balance; its conditions must not encode them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from glovebox.agent.loop import DiscoveryAgent
from glovebox.agent.overfit import overfit_reason
from glovebox.agent.recorder import Recorder
from glovebox.schema.capability import Capability, Parameter, ParamType

ROOT = Path(__file__).resolve().parents[2]


def _committed_artifact() -> dict:
    return json.loads((ROOT / "capabilities" / "member_savings_balance.json").read_text())


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


def test_should_refuse_to_declare_an_outcome_built_from_run_data() -> None:
    """The model gets a tool error and can retry, rather than the run dying at build time."""
    agent = object.__new__(DiscoveryAgent)
    agent.recorder = _recorder(param_values={"member_id": "100234"})
    with pytest.raises(ValueError, match="100234"):
        DiscoveryAgent._t_declare_outcome(agent, "MEMBER_FOUND", "found", "Member No. 100234")
    assert agent.recorder.outcomes == []


def test_should_reject_a_terminal_outcome_that_matches_the_success_screen() -> None:
    """MEMBER_FOUND ended the run before extraction and returned no outputs."""
    doc = _committed_artifact()
    shadowing = f"{doc['success'][0]['value']} detail"
    doc["outcomes"] = [
        {
            "code": "MEMBER_FOUND",
            "description": "found",
            "detect": {"kind": "text_visible", "value": shadowing, "timeout_ms": 0},
            "terminal": True,
        }
    ]
    with pytest.raises(ValueError, match="MEMBER_FOUND"):
        Capability.model_validate(doc)


def test_should_keep_accepting_the_committed_artifact() -> None:
    assert Capability.model_validate(_committed_artifact()).id == "member_savings_balance"

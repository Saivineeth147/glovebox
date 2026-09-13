"""Replay signs in every time. A warm session is the difference between 2.8s and the work."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from glovebox.replay.engine import ReplayOptions
from glovebox.schema.capability import Capability

ROOT = Path(__file__).resolve().parents[2]


def _capability() -> Capability:
    return Capability.model_validate_json(
        (ROOT / "capabilities" / "member_savings_balance.json").read_text()
    )


def test_should_start_at_the_beginning_by_default() -> None:
    assert ReplayOptions().start_at is None


def test_should_report_the_steps_a_warm_session_lets_it_skip() -> None:
    from glovebox.replay.engine import steps_from

    cap = _capability()
    resumed = steps_from(cap.steps, cap.steps[4].id)
    # The entry navigation is kept: a session is not a screen, so the run still has to arrive
    # where the capability expects before the steps it kept make sense.
    assert [s.id for s in resumed] == [cap.steps[0].id, *[s.id for s in cap.steps[4:]]]


def test_should_refuse_a_step_the_capability_does_not_contain() -> None:
    """A typo here would silently skip the whole flow and report success on an empty run."""
    from glovebox.replay.engine import steps_from

    with pytest.raises(ValueError, match="no step"):
        steps_from(_capability().steps, "s99_nonexistent")


def test_should_keep_every_step_when_no_start_is_given() -> None:
    from glovebox.replay.engine import steps_from

    cap = _capability()
    assert steps_from(cap.steps, None) == cap.steps


def test_a_capability_should_say_which_steps_only_establish_a_session() -> None:
    """The sign-in prefix is what a session-bootstrap capability would own instead."""
    from glovebox.replay.engine import session_prefix

    cap = _capability()
    prefix = session_prefix(cap)
    assert prefix, "no sign-in prefix detected in a flow that signs in"
    assert all(s.risk == "read" or s.action in ("navigate", "fill", "click") for s in prefix)
    assert json.dumps([s.id for s in prefix])

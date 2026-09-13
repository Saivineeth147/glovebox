"""Looking at a state without recording the walk there.

An outcome detector the run never saw is a guess. Walking to that state would normally record
the walk into the capability, so the artifact would carry steps that search for a member that
does not exist. Probing suspends recording while leaving observation intact, which is the only
part needed to confirm a detector.
"""

from __future__ import annotations

import pytest

from glovebox.agent.recorder import Recorder
from glovebox.schema.capability import Parameter, ParamType, Target, TargetStrategy


def _recorder() -> Recorder:
    return Recorder(
        capability_id="c",
        app_id="a",
        tenant=None,
        entry_url="http://127.0.0.1:8089/t/alpha/",
        params=[Parameter(name="member_id", type=ParamType.STRING, description="d")],
        model_name="test",
        run_id="r",
    )


def _target() -> Target:
    return Target(
        description="cell",
        strategies=[TargetStrategy(kind="text", value={"text": "S01"}, robustness="r")],
    )


def _finish(rec: Recorder):
    return rec.build(
        title="t",
        description="d",
        success_text=["Share Accounts"],
        transcript=[],
        surface_name="TestSurface",
    )


def test_should_not_record_a_step_taken_while_probing() -> None:
    rec = _recorder()
    rec.navigate("http://127.0.0.1:8089/t/alpha/", "open the application entry point")
    rec.extract(_target(), "savings_balance", "balance", "string", None)
    rec.paused = True
    rec.click(_target(), "search for a member that does not exist", "read")
    rec.paused = False
    assert [str(s.action) for s in _finish(rec).steps] == ["navigate", "extract"]


def test_should_not_declare_an_output_discovered_while_probing() -> None:
    rec = _recorder()
    rec.navigate("http://127.0.0.1:8089/t/alpha/", "open the application entry point")
    rec.extract(_target(), "savings_balance", "balance", "string", None)
    rec.paused = True
    rec.extract(_target(), "stray_value", "seen while probing", "string", None)
    rec.paused = False
    assert [o.name for o in _finish(rec).outputs] == ["savings_balance"]


def test_should_still_remember_text_seen_while_probing() -> None:
    """The whole point: the detector is confirmed by what probing saw."""
    rec = _recorder()
    rec.paused = True
    rec.note_observed_text("No member record matched number 999999.")
    rec.paused = False
    rec.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member record matched")
    rec.navigate("http://127.0.0.1:8089/t/alpha/", "open the application entry point")
    rec.extract(_target(), "savings_balance", "balance", "string", None)
    assert _finish(rec).outcomes[0].verified is True


def test_should_refuse_to_build_while_still_probing() -> None:
    """A capability built mid-probe would be missing the steps taken since it began."""
    rec = _recorder()
    rec.navigate("http://127.0.0.1:8089/t/alpha/", "open the application entry point")
    rec.extract(_target(), "savings_balance", "balance", "string", None)
    rec.paused = True
    with pytest.raises(RuntimeError, match="probe"):
        _finish(rec)


def _agent_with(rec: Recorder):
    from glovebox.agent.loop import DiscoveryAgent

    agent = object.__new__(DiscoveryAgent)
    agent.recorder = rec
    agent.log = type("L", (), {"emit": lambda *a, **k: None})()
    agent._nudged_about_outcomes = False
    return agent


def test_should_open_and_close_a_probe_through_the_tools() -> None:
    from glovebox.agent.loop import DiscoveryAgent

    agent = _agent_with(_recorder())
    DiscoveryAgent._t_begin_probe(agent, "look at the not-found screen")
    assert agent.recorder.paused is True
    DiscoveryAgent._t_end_probe(agent)
    assert agent.recorder.paused is False


def test_should_refuse_to_open_a_second_probe() -> None:
    from glovebox.agent.loop import DiscoveryAgent

    agent = _agent_with(_recorder())
    DiscoveryAgent._t_begin_probe(agent, "first")
    with pytest.raises(ValueError, match="already open"):
        DiscoveryAgent._t_begin_probe(agent, "second")


def test_should_refuse_to_close_a_probe_that_was_never_opened() -> None:
    from glovebox.agent.loop import DiscoveryAgent

    with pytest.raises(ValueError, match="no probe"):
        DiscoveryAgent._t_end_probe(_agent_with(_recorder()))


def test_should_refuse_to_finish_while_a_probe_is_open() -> None:
    """Finishing mid-probe would silently drop every step taken since it began."""
    from glovebox.agent.loop import DiscoveryAgent

    agent = _agent_with(_recorder())
    agent.recorder.paused = True
    with pytest.raises(ValueError, match="probe is still open"):
        DiscoveryAgent._t_finish(agent, ["Share Accounts"], "summary", "title")


def test_should_record_an_outcome_declared_while_probing() -> None:
    """Reading the wording is why the probe exists; discarding it would defeat the feature."""
    rec = _recorder()
    rec.navigate("http://127.0.0.1:8089/t/alpha/", "open the application entry point")
    rec.extract(_target(), "savings_balance", "balance", "string", None)
    rec.paused = True
    rec.note_observed_text("No member record matched number 999999.")
    rec.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member record matched")
    rec.paused = False
    outcome = _finish(rec).outcomes[0]
    assert outcome.code == "MEMBER_NOT_FOUND" and outcome.verified is True


def test_should_refuse_a_recovery_declared_while_probing() -> None:
    """A recovery carries the locator that dismisses it, taken from a screen replay never sees."""
    from glovebox.agent.loop import DiscoveryAgent

    agent = _agent_with(_recorder())
    agent.recorder.paused = True
    with pytest.raises(ValueError, match="probed screen"):
        DiscoveryAgent._t_declare_recovery(agent, "stale_dialog", "Notice", "e1")


def test_should_refuse_to_finish_with_an_outcome_the_run_never_saw() -> None:
    """Prompt guidance did not get the model to probe; a tool error is what does."""
    from glovebox.agent.loop import DiscoveryAgent

    agent = _agent_with(_recorder())
    agent.recorder.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member found")
    with pytest.raises(ValueError, match="MEMBER_NOT_FOUND"):
        DiscoveryAgent._t_finish(agent, ["Share Accounts"], "summary", "title")


def test_should_allow_finishing_once_the_detector_has_been_seen() -> None:
    from glovebox.agent.loop import DiscoveryAgent

    agent = _agent_with(_recorder())
    agent.surface = type("S", (), {"check": lambda *a, **k: (True, "")})()
    agent.recorder.note_observed_text("No member record matched number 999999.")
    agent.recorder.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member record matched")
    agent._finish = None
    from glovebox.agent.loop import _Finished

    # _t_finish ends the run by raising; reaching that is what "allowed through" means here.
    with pytest.raises(_Finished):
        DiscoveryAgent._t_finish(agent, ["Share Accounts"], "summary", "title")
    assert agent._finish is not None


def test_should_let_the_model_drop_an_outcome_it_cannot_substantiate() -> None:
    """The escape from the guard: withdraw the claim rather than assert it unverified."""
    from glovebox.agent.loop import DiscoveryAgent

    agent = _agent_with(_recorder())
    agent.recorder.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member found")
    DiscoveryAgent._t_drop_outcome(agent, "MEMBER_NOT_FOUND")
    assert agent.recorder.outcomes == []


def test_should_refuse_to_drop_an_outcome_that_was_never_declared() -> None:
    from glovebox.agent.loop import DiscoveryAgent

    with pytest.raises(ValueError, match="not declared"):
        DiscoveryAgent._t_drop_outcome(_agent_with(_recorder()), "NOPE")

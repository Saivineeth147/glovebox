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

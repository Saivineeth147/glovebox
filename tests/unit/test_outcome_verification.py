"""An outcome detector the run never saw is a guess, and the catalog must not present it as fact."""

from __future__ import annotations

from pathlib import Path

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


def _build(rec: Recorder):
    rec.navigate("http://127.0.0.1:8089/t/alpha/", "open the application entry point")
    rec.extract(
        Target(
            description="cell 'Current Balance' in row 'S01'",
            strategies=[TargetStrategy(kind="text", value={"text": "S01"}, robustness="r")],
        ),
        "savings_balance",
        "current balance",
        "string",
        None,
    )
    return rec.build(
        title="t",
        description="d",
        success_text=["Share Accounts"],
        transcript=[],
        surface_name="TestSurface",
    )


def test_should_mark_an_outcome_verified_when_its_detector_text_was_seen() -> None:
    rec = _recorder()
    rec.note_observed_text("MENU Member Inquiry No member record matched number 999999.")
    rec.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member record matched")
    cap = _build(rec)
    assert cap.outcomes[0].verified is True


def test_should_mark_an_outcome_unverified_when_the_run_never_saw_that_text() -> None:
    """The model guessed 'No member found'; the app says 'No member record matched'."""
    rec = _recorder()
    rec.note_observed_text("MENU Member Inquiry Member Detail Share Accounts Regular Savings")
    rec.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member found")
    cap = _build(rec)
    assert cap.outcomes[0].verified is False


def test_should_verify_text_seen_after_the_outcome_was_declared() -> None:
    """Order of declaration must not decide the verdict; the whole run is the evidence."""
    rec = _recorder()
    rec.declare_outcome("MEMBER_NOT_FOUND", "no match", "No member record matched")
    rec.note_observed_text("No member record matched number 999999.")
    cap = _build(rec)
    assert cap.outcomes[0].verified is True


def test_should_refuse_to_approve_a_capability_carrying_an_unverified_terminal_outcome(
    tmp_path,
) -> None:
    """Approval is where a guessed detector must be caught; it cannot be caught later."""
    import json

    from typer.testing import CliRunner

    from glovebox import cli

    doc = json.loads(Path("capabilities/member_savings_balance.json").read_text())
    doc["review"] = {"status": "draft", "replays": 0, "replay_successes": 0}
    doc["outcomes"] = [
        {
            "code": "MEMBER_NOT_FOUND",
            "description": "no match",
            "detect": {"kind": "text_visible", "value": "No member found", "timeout_ms": 0},
            "terminal": True,
            "verified": False,
        }
    ]
    (tmp_path / "member_savings_balance.json").write_text(json.dumps(doc))

    result = CliRunner().invoke(
        cli.app,
        ["catalog", "approve", "member_savings_balance", "me", "--catalog-dir", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert "MEMBER_NOT_FOUND" in result.output

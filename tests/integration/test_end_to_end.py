"""End-to-end tests: real browser, real (simulated) legacy app, scripted decisions."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from glovebox.catalog import Catalog
from glovebox.control.session import OperatorBridge, ScriptedOperator
from glovebox.drift_eval import (
    DriftEvalOptions,
    evaluate_capability,
    rescues,
    survival_rate,
)
from glovebox.runner import run_replay
from glovebox.schema import (
    ActionKind,
    Capability,
    Condition,
    ConditionKind,
    Policy,
    Recovery,
    ReplayStatus,
    Step,
    Target,
    TargetStrategy,
    TenantOverride,
)
from tests.conftest import creds

pytestmark = pytest.mark.integration


def _arm(app_url: str, fault: str) -> None:
    httpx.post(f"{app_url}/__sim/faults/{fault}", timeout=5).raise_for_status()


# ----------------------------------------------------------------------------- discovery artifact
def test_discovery_produces_reviewable_parameterized_artifact(savings_capability: Capability):
    cap = savings_capability
    assert cap.id == "member_savings_balance" and cap.review.status == "approved"
    assert {p.name for p in cap.inputs} == {"username", "password", "member_id"}
    assert all(p.sensitive for p in cap.inputs if p.name in {"username", "password"})
    assert {o.name for o in cap.outputs} == {"savings_balance", "member_name"}
    fills = [s for s in cap.steps if s.action == ActionKind.FILL]
    assert {s.value for s in fills} == {
        "{{ params.username }}",
        "{{ params.password }}",
        "{{ params.member_id }}",
    }
    assert [o.code for o in cap.outcomes] == ["MEMBER_NOT_FOUND"]
    assert any(r.name == "session_expired" for r in cap.recoveries)
    assert cap.max_risk == "reversible"
    dumped = cap.model_dump_json()
    assert "teller1-pass" not in dumped and "100234" not in dumped  # parameterized, no secrets


def test_discovery_evidence_is_redacted(savings_capability: Capability, runs_dir: Path):
    run = runs_dir / savings_capability.provenance.discovery_run_id
    events = (run / "events.jsonl").read_text()
    transcript = (run / "transcript.json").read_text()
    assert "teller1-pass" not in events and "teller1-pass" not in transcript
    assert "[REDACTED:password#" in events or "[REDACTED:password" in transcript
    kinds = {json.loads(line)["kind"] for line in events.splitlines()}
    assert {
        "run.started",
        "surface.observation",
        "surface.action",
        "policy.decision",
        "run.finished",
    } <= kinds
    assert list((run / "screenshots").glob("*.png"))


# ----------------------------------------------------------------------------- replay: outcomes
def test_replay_success_with_different_input(savings_capability, policy, runs_dir):
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100235"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert r.outputs == {"savings_balance": 18930.0, "member_name": "Ng, Marcus"}
    assert all(s.status == "ok" for s in r.steps)
    assert (Path(r.evidence_dir) / "result.json").exists()


def test_replay_reports_business_outcome_not_failure(savings_capability, policy, runs_dir):
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "999999"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.BUSINESS_OUTCOME
    assert r.outcome_code == "MEMBER_NOT_FOUND" and r.failure is None and r.outputs == {}


def test_replay_rejects_invalid_input_before_touching_the_app(savings_capability, policy, runs_dir):
    r = run_replay(
        savings_capability, {**creds(), "member_id": "abc"}, policy, runs_dir=runs_dir, trace=False
    )
    assert r.status == ReplayStatus.FAILED and r.failure.failure_class == "input_invalid"
    assert r.steps == []


def test_replay_refuses_unapproved_draft(savings_capability, policy, runs_dir):
    draft = savings_capability.model_copy(deep=True)
    draft.review.status = "draft"
    r = run_replay(
        draft, {**creds(), "member_id": "100234"}, policy, runs_dir=runs_dir, trace=False
    )
    assert r.status == ReplayStatus.FAILED and r.failure.failure_class == "not_approved"
    ok = run_replay(
        draft,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        allow_draft=True,
        trace=False,
    )
    assert ok.status == ReplayStatus.SUCCESS


# ----------------------------------------------------------------------------- replay: runtime faults
def test_app_error_is_a_hard_failure_with_evidence(savings_capability, policy, runs_dir, app_url):
    _arm(app_url, "app_error")
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.FAILED
    assert r.failure.failure_class == "failure_signal" and r.failure.step_id
    assert Path(r.failure.evidence["screenshot"]).exists()
    assert any(k.startswith("snapshot:") for k in r.failure.evidence)


def test_session_expiry_is_recovered_by_restart(savings_capability, policy, runs_dir, app_url):
    _arm(app_url, "session_expired")  # fires on the first guarded request after login
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert any(s.status == "recovered" and "session_expired" in s.recoveries for s in r.steps)
    assert r.outputs["savings_balance"] == 1250.75


def test_slow_load_is_absorbed_by_waits(savings_capability, policy, runs_dir, app_url):
    _arm(app_url, "slow")
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.SUCCESS, r.failure


def test_unknown_interstitial_escalates_and_human_dismisses_it(
    savings_capability, policy, runs_dir, app_url
):
    """The interstitial is not declared in the artifact → automation is stuck → human clears it → resume."""
    _arm(app_url, "interstitial")
    bridge = OperatorBridge()
    op = ScriptedOperator(
        bridge,
        [
            {"op": "observe"},
            {"op": "click", "find": {"role": "button", "name": "OK"}},
            {"op": "fill", "find": {"name_attr": "member_no"}, "text": "100234"},
            {"op": "resume"},
        ],
    ).start()
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        bridge=bridge,
        attended=True,
        trace=False,
    )
    op.join()
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert r.handoff and r.handoff.resolution == "resume" and r.handoff.human_actions == 2
    events = [
        json.loads(l) for l in (Path(r.evidence_dir) / "events.jsonl").read_text().splitlines()
    ]
    kinds = [e["kind"] for e in events]
    assert "control.intervention" in kinds and "control.human_action" in kinds
    transitions = [e["data"] for e in events if e["kind"] == "control.transition"]
    assert [(t["from_"], t["to"]) for t in transitions] == [
        ("automation", "human"),
        ("human", "automation"),
    ]
    human = next(e for e in events if e["kind"] == "control.human_action")
    assert human["data"]["target"]["description"] == "button 'OK'"


def test_unknown_interstitial_unattended_is_a_debuggable_failure(
    savings_capability, policy, runs_dir, app_url
):
    _arm(app_url, "interstitial")
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.FAILED
    assert r.failure.failure_class in {"target_not_found", "checkpoint_failed"}
    assert r.failure.step_id and r.failure.expected and r.failure.observed


def test_declared_interstitial_is_recovered_without_a_human(
    savings_capability, policy, runs_dir, app_url
):
    cap = savings_capability.model_copy(deep=True)
    cap.recoveries.append(
        Recovery(
            name="batch_notice",
            then="retry_step",
            detect=Condition(
                kind=ConditionKind.TEXT_VISIBLE,
                value="Nightly batch posting completed",
                timeout_ms=0,
            ),
            actions=[
                Step(
                    id="r_dismiss",
                    action=ActionKind.CLICK,
                    intent="acknowledge notice",
                    target=Target(
                        description="OK",
                        frame=["main"],
                        strategies=[
                            TargetStrategy(
                                kind="role_name",
                                value={"role": "button", "name": "OK"},
                                robustness="",
                            )
                        ],
                    ),
                )
            ],
        )
    )
    _arm(app_url, "interstitial")
    r = run_replay(cap, {**creds(), "member_id": "100234"}, policy, runs_dir=runs_dir, trace=False)
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert any("batch_notice" in s.recoveries for s in r.steps)


def test_operator_timeout_yields_escalated(savings_capability, policy, runs_dir, app_url):
    _arm(app_url, "interstitial")
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        bridge=OperatorBridge(),
        attended=True,
        handoff_timeout_s=1.0,
        trace=False,
    )
    assert r.status == ReplayStatus.ESCALATED and r.handoff.resolution == "timed_out"


# ----------------------------------------------------------------------------- policy
def test_policy_blocks_navigation_outside_allowlist(savings_capability, policy, runs_dir):
    cap = savings_capability.model_copy(deep=True)
    cap.steps[0] = cap.steps[0].model_copy(update={"value": "/__sim/faults"})
    r = run_replay(cap, {**creds(), "member_id": "100234"}, policy, runs_dir=runs_dir, trace=False)
    assert r.status == ReplayStatus.FAILED and r.failure.failure_class == "policy_violation"
    assert r.failure.step_id == cap.steps[0].id


# ----------------------------------------------------------------------------- irreversible flow
def test_irreversible_capability_needs_human_and_yields_reference(
    subaccount_capability, policy, runs_dir
):
    cap = subaccount_capability
    assert cap.max_risk == "irreversible"
    assert any(s.action == ActionKind.EXPECT_DIALOG for s in cap.steps)
    params = {**creds(), "member_id": "100234", "product": "Money Market", "nickname": "Rainy day"}
    blocked = run_replay(cap, params, policy, runs_dir=runs_dir, trace=False)
    assert (
        blocked.status == ReplayStatus.FAILED
        and blocked.failure.failure_class == "policy_violation"
    )
    bridge = OperatorBridge()
    op = ScriptedOperator(bridge, [{"op": "approve"}]).start()
    r = run_replay(
        cap, params, policy, runs_dir=runs_dir, bridge=bridge, attended=True, trace=False
    )
    op.join()
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert r.outputs["reference"].startswith("SA-") and r.handoff.resolution == "approve"
    bridge2 = OperatorBridge()
    op2 = ScriptedOperator(bridge2, [{"op": "decline"}]).start()
    d = run_replay(
        cap, params, policy, runs_dir=runs_dir, bridge=bridge2, attended=True, trace=False
    )
    op2.join()
    assert d.status == ReplayStatus.ESCALATED


def test_irreversible_flow_reports_access_denied_outcome(subaccount_capability, policy, runs_dir):
    bridge = OperatorBridge()
    op = ScriptedOperator(bridge, [{"op": "approve"}]).start()
    r = run_replay(
        subaccount_capability,
        {**creds(), "member_id": "100999", "product": "Holiday Club", "nickname": "x"},
        policy,
        runs_dir=runs_dir,
        bridge=bridge,
        attended=True,
        trace=False,
    )
    op.join()
    assert r.status == ReplayStatus.BUSINESS_OUTCOME and r.outcome_code == "ACCESS_DENIED"


# ----------------------------------------------------------------------------- multi-tenant
def test_capability_recorded_on_alpha_replays_on_bravo_with_override(
    savings_capability, policy, runs_dir
):
    """Bravo renames the label, the button, and shows a post-login notice. One override handles it."""
    cap = savings_capability.model_copy(deep=True)
    cap.overrides.append(
        TenantOverride(
            tenant="bravo",
            entry_path="/t/bravo/",
            step_values={},
            extra_recoveries=[
                Recovery(
                    name="post_login_notice",
                    then="continue",
                    detect=Condition(
                        kind=ConditionKind.TEXT_VISIBLE, value="Scheduled maintenance", timeout_ms=0
                    ),
                    actions=[
                        Step(
                            id="r_ack",
                            action=ActionKind.CLICK,
                            intent="acknowledge maintenance notice",
                            target=Target(
                                description="Acknowledge",
                                frame=["main"],
                                strategies=[
                                    TargetStrategy(
                                        kind="role_name",
                                        value={"role": "button", "name": "Acknowledge"},
                                        robustness="",
                                    )
                                ],
                            ),
                        )
                    ],
                )
            ],
            notes="Bayview labels: 'Member Number' / 'Search'; locators fall through to name_attr, no target override needed",
        )
    )
    r = run_replay(
        cap,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        tenant="bravo",
        trace=False,
    )
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert r.outputs["savings_balance"] == 1250.75
    fill = next(
        s
        for s in r.steps
        if s.step_id.endswith("_fill") and s.strategy_used not in {"role_name", None}
    )
    assert (
        fill.strategy_used == "name_attr"
    )  # label renamed → fell through to the server-bound field name


# ----------------------------------------------------------------------------- catalog
def test_catalog_exposes_capabilities_as_tools(catalog: Catalog, savings_capability):
    tools = catalog.tool_definitions()
    t = next(x for x in tools if x["name"] == "member_savings_balance")
    assert t["input_schema"]["required"] == ["username", "password", "member_id"]
    assert t["input_schema"]["properties"]["member_id"]["pattern"] == r"^\d{6}$"
    assert "MEMBER_NOT_FOUND" in t["description"] and "savings_balance" in t["description"]
    catalog.record_replay("member_savings_balance", True)
    assert catalog.load("member_savings_balance").review.confidence == 1.0


# ----------------------------------------------------------------------------- operator console
def test_operator_console_serves_state_and_forwards_commands(
    savings_capability, policy, runs_dir, app_url
):
    import threading
    import time

    from glovebox.control.console import OperatorConsole
    from glovebox.testing import free_port

    _arm(app_url, "interstitial")
    bridge = OperatorBridge()
    console = OperatorConsole(bridge, port=free_port()).start()

    def human() -> None:
        assert bridge.wait_for_intervention(30)
        time.sleep(0.5)
        c = httpx.Client(base_url=console.url, timeout=30)
        state = c.get("/api/state").json()
        assert state["owner"] == "human" and state["intervention"]["kind"] == "stuck"
        assert c.get("/api/screenshot").status_code == 200
        ok = next(
            e["ref"] for e in state["elements"] if e["role"] == "button" and e["name"] == "OK"
        )
        assert c.post(
            "/api/command", json={"op": "click", "ref": ok, "operator": "console-user"}
        ).json()["ok"]
        state = c.get("/api/state").json()
        assert state["actions"] and state["actions"][0]["target"]["description"] == "button 'OK'"
        field = next(e["ref"] for e in state["elements"] if e["name_attr"] == "member_no")
        assert c.post("/api/command", json={"op": "fill", "ref": field, "text": "100234"}).json()[
            "ok"
        ]
        assert c.post("/api/command", json={"op": "resume"}).json()["ok"]

    t = threading.Thread(target=human, daemon=True)
    t.start()
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        bridge=bridge,
        attended=True,
        trace=False,
    )
    t.join(30)
    console.stop()
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert r.handoff.operator == "console-user"


def test_human_can_restart_the_flow_from_the_top(savings_capability, policy, runs_dir, app_url):
    _arm(app_url, "interstitial")
    bridge = OperatorBridge()
    op = ScriptedOperator(
        bridge,
        [
            {"op": "observe"},
            {"op": "click", "find": {"role": "button", "name": "OK"}},
            {"op": "restart"},
        ],
    ).start()
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        bridge=bridge,
        attended=True,
        trace=False,
    )
    op.join()
    assert r.status == ReplayStatus.SUCCESS, r.failure
    assert r.handoff.resolution == "restart"
    assert [s.step_id for s in r.steps].count("s01_navigate") == 2


@pytest.mark.integration
def test_capability_survives_a_redesign_through_a_lower_locator_strategy(
    savings_capability: Capability,
    policy: Policy,
    runs_dir: Path,
    app_url: str,
) -> None:
    """The locator ladder is the design's central claim; this measures it instead of asserting.

    Renaming the search control breaks the recorded role+name, so the step must resolve through
    a lower rung. A survival with no change of strategy would mean the mutation missed.
    """
    options = DriftEvalOptions(
        target_url=app_url,
        runs_dir=str(runs_dir),
        drifts=("rename_action",),
    )
    baseline, results = evaluate_capability(
        savings_capability, {"member_id": "100234", **creds()}, policy, options
    )

    assert baseline.survived, baseline.failure_class
    assert survival_rate(results) == 1.0
    assert rescues(baseline.strategies, results[0].strategies), (
        "renaming the control changed nothing, so the mutation did not reach the recorded locator"
    )

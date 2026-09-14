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
from glovebox.schema.capability import ReviewStatus
from tests.conftest import creds

pytestmark = pytest.mark.integration


def _arm(app_url: str, fault: str) -> None:
    httpx.post(f"{app_url}/__sim/faults/{fault}", timeout=5).raise_for_status()


# ----------------------------------------------------------------------------- discovery artifact
def test_discovery_produces_reviewable_parameterized_artifact(
    savings_capability: Capability,
) -> None:
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


def test_discovery_evidence_is_redacted(savings_capability: Capability, runs_dir: Path) -> None:
    run = runs_dir / savings_capability.provenance.discovery_run_id
    events = (run / "events.jsonl").read_text()
    transcript = (run / "transcript.json").read_text()
    assert "teller1-pass" not in events and "teller1-pass" not in transcript
    assert "teller1" not in events and "teller1" not in transcript
    # Absence alone would also hold if the prompt never mentioned the parameter. The model has to
    # see that a credential exists and is withheld, so it must appear as a visible placeholder.
    # This asserted "[REDACTED:password" before, which only held because the pattern redactor was
    # re-redacting a value already substituted as "<hidden:" and mangling it in the process.
    assert "<hidden:" in transcript
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
def test_replay_success_with_different_input(
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
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


def test_replay_reports_business_outcome_not_failure(
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "999999"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.BUSINESS_OUTCOME
    assert r.outcome_code == "MEMBER_NOT_FOUND" and r.failure is None and r.outputs == {}


def test_replay_rejects_invalid_input_before_touching_the_app(
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
    r = run_replay(
        savings_capability, {**creds(), "member_id": "abc"}, policy, runs_dir=runs_dir, trace=False
    )
    assert r.failure is not None
    assert r.status == ReplayStatus.FAILED and r.failure.failure_class == "input_invalid"
    assert r.steps == []


def test_replay_refuses_unapproved_draft(
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
    draft = savings_capability.model_copy(deep=True)
    draft.review.status = ReviewStatus.DRAFT
    r = run_replay(
        draft, {**creds(), "member_id": "100234"}, policy, runs_dir=runs_dir, trace=False
    )
    assert r.failure is not None
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
def test_app_error_is_a_hard_failure_with_evidence(
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
    _arm(app_url, "app_error")
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.FAILED
    assert r.failure is not None
    assert r.failure.failure_class == "failure_signal" and r.failure.step_id
    assert Path(r.failure.evidence["screenshot"]).exists()
    assert any(k.startswith("snapshot:") for k in r.failure.evidence)


def test_session_expiry_is_recovered_by_restart(
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
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


def test_slow_load_is_absorbed_by_waits(
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
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
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
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
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
    _arm(app_url, "interstitial")
    r = run_replay(
        savings_capability,
        {**creds(), "member_id": "100234"},
        policy,
        runs_dir=runs_dir,
        trace=False,
    )
    assert r.status == ReplayStatus.FAILED
    assert r.failure is not None
    assert r.failure.failure_class in {"target_not_found", "checkpoint_failed"}
    assert r.failure.step_id and r.failure.expected and r.failure.observed


def test_declared_interstitial_is_recovered_without_a_human(
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
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


def test_operator_timeout_yields_escalated(
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
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
    assert r.handoff is not None
    assert r.status == ReplayStatus.ESCALATED and r.handoff.resolution == "timed_out"


# ----------------------------------------------------------------------------- policy
def test_policy_blocks_navigation_outside_allowlist(
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
    cap = savings_capability.model_copy(deep=True)
    cap.steps[0] = cap.steps[0].model_copy(update={"value": "/__sim/faults"})
    r = run_replay(cap, {**creds(), "member_id": "100234"}, policy, runs_dir=runs_dir, trace=False)
    assert r.failure is not None
    assert r.status == ReplayStatus.FAILED and r.failure.failure_class == "policy_violation"
    assert r.failure.step_id == cap.steps[0].id


# ----------------------------------------------------------------------------- irreversible flow
def test_irreversible_capability_needs_human_and_yields_reference(
    subaccount_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
    cap = subaccount_capability
    assert cap.max_risk == "irreversible"
    assert any(s.action == ActionKind.EXPECT_DIALOG for s in cap.steps)
    params = {**creds(), "member_id": "100234", "product": "Money Market", "nickname": "Rainy day"}
    blocked = run_replay(cap, params, policy, runs_dir=runs_dir, trace=False)
    assert blocked.failure is not None
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
    assert r.handoff is not None
    assert r.outputs["reference"].startswith("SA-") and r.handoff.resolution == "approve"
    bridge2 = OperatorBridge()
    op2 = ScriptedOperator(bridge2, [{"op": "decline"}]).start()
    d = run_replay(
        cap, params, policy, runs_dir=runs_dir, bridge=bridge2, attended=True, trace=False
    )
    op2.join()
    assert d.status == ReplayStatus.ESCALATED


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fault", "expected_code"),
    [("permission_denied", "ACCESS_DENIED"), ("validation", "VALIDATION_ERROR")],
)
def test_a_refused_submit_is_an_outcome_the_caller_can_branch_on(
    subaccount_capability: Capability,
    policy: Policy,
    runs_dir: Path,
    app_url: str,
    fault: str,
    expected_code: str,
) -> None:
    """The two faults that only the mutating flow can raise, and the claim they back.

    `permission_denied` and `validation` fire on the sub-account submit, so no lookup capability
    can reach them and nothing exercised them. That left the README's "every injected fault"
    unbacked, and left the taxonomy's most consequential row — a refused write reported as an
    answer rather than a crash — resting on the two outcomes that happen to be read-only.
    """
    params = {**creds(), "member_id": "100234", "product": "Money Market", "nickname": "Rainy day"}
    _arm(app_url, fault)
    bridge = OperatorBridge()
    operator = ScriptedOperator(bridge, [{"op": "approve"}]).start()

    r = run_replay(
        subaccount_capability,
        params,
        policy,
        runs_dir=runs_dir,
        bridge=bridge,
        attended=True,
        trace=False,
    )
    operator.join()

    assert r.status == ReplayStatus.BUSINESS_OUTCOME, r.failure
    assert r.outcome_code == expected_code
    assert r.failure is None  # a refused write is an answer, not a failure
    assert not r.ok and r.answered


@pytest.mark.integration
def test_an_extraction_that_loses_its_recorded_shape_fails_instead_of_guessing(
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
    """The taxonomy row with no test: a regex miss must not report whatever was on screen.

    Returning the raw cell on a miss is how a member number gets reported as a savings balance
    and the caller cannot tell. The failure has to name the step and show both sides.
    """
    cap = savings_capability.model_copy(deep=True)
    for step in cap.steps:
        if step.extract_to:
            step.value = r"ACCOUNT-(\d{9})"  # a shape this cell will never have

    r = run_replay(cap, {**creds(), "member_id": "100234"}, policy, runs_dir=runs_dir, trace=False)

    assert r.status == ReplayStatus.FAILED
    assert r.failure is not None
    assert r.failure.failure_class == "checkpoint_failed"
    assert r.failure.step_id and r.failure.step_id.endswith("_extract")
    assert "ACCOUNT-" in (r.failure.expected or "")
    assert "1250.75" in (r.failure.observed or "")
    assert r.outputs == {}  # nothing plausible-but-wrong handed back


@pytest.mark.integration
def test_a_detector_the_recorder_verified_must_also_fire_at_replay(
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
    """The two halves of `verified` have to normalise text the same way.

    The recorder collapses whitespace before deciding a detector was seen, because a legacy page
    splits one sentence across table cells. Replay used a raw substring test, so a detector could
    be recorded verified and never fire — the capability then reports a hard failure exactly where
    its contract promised a business outcome.
    """
    cap = savings_capability.model_copy(deep=True)
    assert cap.outcomes, "fixture should carry the not-found outcome"
    outcome = cap.outcomes[0]
    assert outcome.verified, "the recorder marked this detector as seen during the run"
    # Re-space the detector the way a page break would; the recorder would still call it seen.
    detector = outcome.detect.value or ""
    outcome.detect.value = "\n   ".join(detector.split(" ", 1))

    r = run_replay(cap, {**creds(), "member_id": "999999"}, policy, runs_dir=runs_dir, trace=False)

    assert r.status == ReplayStatus.BUSINESS_OUTCOME, r.failure
    assert r.outcome_code == outcome.code


def test_irreversible_flow_reports_access_denied_outcome(
    subaccount_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
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
    savings_capability: Capability, policy: Policy, runs_dir: Path
) -> None:
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
def test_catalog_exposes_capabilities_as_tools(
    catalog: Catalog, savings_capability: Capability
) -> None:
    tools = catalog.tool_definitions()
    t = next(x for x in tools if x["name"] == "member_savings_balance")
    assert t["input_schema"]["required"] == ["username", "password", "member_id"]
    assert t["input_schema"]["properties"]["member_id"]["pattern"] == r"^\d{6}$"
    assert "MEMBER_NOT_FOUND" in t["description"] and "savings_balance" in t["description"]
    catalog.record_replay("member_savings_balance", True)
    assert catalog.load("member_savings_balance").review.confidence == 1.0


# ----------------------------------------------------------------------------- operator console
def test_operator_console_serves_state_and_forwards_commands(
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
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
    assert r.handoff is not None
    assert r.handoff.operator == "console-user"


def test_human_can_restart_the_flow_from_the_top(
    savings_capability: Capability, policy: Policy, runs_dir: Path, app_url: str
) -> None:
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
    assert r.handoff is not None
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


@pytest.mark.integration
def test_the_scripted_flow_verifies_its_outcome_detector_by_probing(
    savings_capability: Capability,
) -> None:
    """The detector's wording is read off the real screen, not guessed, and the walk there
    leaves no trace in the recorded steps."""
    outcome = next(o for o in savings_capability.outcomes if o.code == "MEMBER_NOT_FOUND")
    assert outcome.verified is True
    assert not any(step.value == "999999" for step in savings_capability.steps), (
        "the probe's bogus search was recorded into the capability"
    )


@pytest.mark.integration
def test_the_same_capability_replays_through_a_surface_with_no_browser(
    policy: Policy,
    runs_dir: Path,
    app_url: str,
) -> None:
    """Seam 1, tested rather than argued.

    The artifact was recorded through Playwright. Replaying it through a surface with no DOM,
    no JavaScript and no layout engine — resolved by the same locators module — is what makes
    "the vocabulary is surface-agnostic" a fact instead of a design intention.
    """
    from glovebox.surface.http.html_surface import HtmlSurface

    committed = Catalog(Path(__file__).resolve().parents[2] / "capabilities").load(
        "member_savings_balance"
    )

    result = run_replay(
        committed,
        {"member_id": "100234", **creds()},
        policy,
        runs_dir=runs_dir,
        allow_draft=True,
        trace=False,
        surface_factory=lambda run_dir: HtmlSurface(app_url, evidence_dir=run_dir.root),
    )

    assert result.status == ReplayStatus.SUCCESS, result.failure
    # Not float(...) == 1250.75: that passes for the string this capability must never return,
    # which is the regression the typed-output contract exists to prevent.
    assert result.outputs["savings_balance"] == 1250.75
    assert isinstance(result.outputs["savings_balance"], float)


@pytest.mark.integration
def test_a_broken_locator_gets_a_reviewable_proposal_and_the_run_still_fails(
    savings_capability: Capability,
    policy: Policy,
    runs_dir: Path,
    app_url: str,
) -> None:
    """Assisted repair, under a real redesign: the model suggests, the run still fails.

    A capability that healed itself would put a model back in the production path and hand a
    reviewer an artifact nobody approved. So the proposal is written beside the evidence and
    the replay reports the failure exactly as it would have without it.
    """
    import json as _json

    class _RenameAwareLLM:
        """Stands in for the model: reads the screen, names the renamed control."""

        def complete(self, system: str, prompt: str) -> str:
            return _json.dumps(
                {"kind": "role_name", "value": {"role": "button", "name": "Locate Member"}}
            )

    broken = savings_capability.model_copy(
        update={
            "steps": [
                s.model_copy(
                    update={
                        "target": s.target.model_copy(
                            update={
                                "strategies": [
                                    s.target.strategies[0].model_copy(
                                        update={"value": {"role": "button", "name": "Gone Forever"}}
                                    )
                                ]
                            }
                        )
                    }
                )
                if s.target and s.target.description == "button 'Find Member'"
                else s
                for s in savings_capability.steps
            ]
        }
    )
    httpx.post(f"{app_url}/__sim/drift/rename_action", timeout=10)
    try:
        result = run_replay(
            broken,
            {"member_id": "100234", **creds()},
            policy,
            runs_dir=runs_dir,
            allow_draft=True,
            trace=False,
            repair=_RenameAwareLLM(),
        )
    finally:
        httpx.request("DELETE", f"{app_url}/__sim/drift", timeout=10)

    assert result.status == ReplayStatus.FAILED
    proposal = Path(result.evidence_dir) / "repair-proposal.json"
    assert proposal.exists(), "no proposal was written for an unresolvable target"
    saved = _json.loads(proposal.read_text())
    assert saved["status"] == "proposed"
    assert saved["strategy"]["value"]["name"] == "Locate Member"


@pytest.mark.integration
def test_a_warm_session_lets_a_replay_skip_signing_in_again(
    policy: Policy,
    runs_dir: Path,
    app_url: str,
) -> None:
    """Glovebox-Design-Writeup.md §7's first cut: every replay signs in, and it does not have to.

    The first run establishes the session. The second starts after the sign-in prefix and is
    given no credentials at all, which is the point — a reused session keeps them out of the
    main flow entirely, not merely out of the log.
    """
    from glovebox.replay.engine import session_prefix
    from glovebox.surface.http.html_surface import HtmlSurface

    committed = Catalog(Path(__file__).resolve().parents[2] / "capabilities").load(
        "member_savings_balance"
    )
    prefix = session_prefix(committed)
    assert prefix, "no sign-in prefix found to skip"
    resume_at = committed.steps[len(prefix)].id

    warm = HtmlSurface(app_url)
    try:
        first = run_replay(
            committed,
            {"member_id": "100234", **creds()},
            policy,
            runs_dir=runs_dir,
            allow_draft=True,
            trace=False,
            surface=warm,
        )
        assert first.status == ReplayStatus.SUCCESS, first.failure

        without_credentials = run_replay(
            committed,
            {"member_id": "100235"},
            policy,
            runs_dir=runs_dir,
            allow_draft=True,
            trace=False,
            surface=warm,
            start_at=resume_at,
        )
    finally:
        warm.close()

    assert without_credentials.status == ReplayStatus.SUCCESS, without_credentials.failure
    assert float(without_credentials.outputs["savings_balance"]) == 18930.0
    assert len(without_credentials.steps) < len(first.steps)

"""Regenerate the replay evidence bundles under evidence/ (offline, no model).

Discovery evidence is different: it must come from a *real* LLM-driven run, so it is produced
by `make discover` with an API key and is not touched here. Each bundle below is a replay of
the committed capability artifact against the simulated legacy app with a specific runtime
condition, plus one offline (scripted) discovery so the artifact-generation path is visible.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from glovebox.agent.llm import ScriptedLLM
from glovebox.agent.scripts import MEMBER_SAVINGS_BALANCE, standard_params
from glovebox.catalog import Catalog
from glovebox.control.session import OperatorBridge, ScriptedOperator
from glovebox.runner import run_discovery, run_replay
from glovebox.schema import Parameter, ParamType, Policy
from glovebox.testing import target_app

EVIDENCE = ROOT / "evidence"
RUNS = ROOT / "runs"
PORT = 8089


def bundle(name: str, run_dir: str | Path, extra: dict[str, Any] | None = None) -> None:
    dst = EVIDENCE / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(run_dir, dst, ignore=shutil.ignore_patterns("trace.zip"))
    if extra:
        (dst / "SUMMARY.json").write_text(json.dumps(extra, indent=2, default=str))
    print(f"  -> evidence/{name}")


def main() -> None:
    os.environ.setdefault("GLOVEBOX_APP_USERNAME", "teller1")
    os.environ.setdefault("GLOVEBOX_APP_PASSWORD", "teller1-pass")
    policy = Policy.load(ROOT / "policies" / "default.yaml")
    catalog = Catalog(ROOT / "capabilities")
    creds = {
        "username": os.environ["GLOVEBOX_APP_USERNAME"],
        "password": os.environ["GLOVEBOX_APP_PASSWORD"],
    }

    with target_app(PORT) as base:
        std = standard_params(base)

        # 0. offline discovery — shows the artifact-generation path without a model. Clearly labelled.
        print("offline discovery (scripted, no model)")
        res = run_discovery(
            goal="Look up member 100234 and read their current savings balance",
            entry_url=std["entry"],
            params={**std["values"], "member_id": "100234"},
            param_specs=[
                *std["specs"],
                Parameter(
                    name="member_id",
                    type=ParamType.STRING,
                    description="Member number to look up",
                    pattern=r"^\d{6}$",
                    example="100234",
                ),
            ],
            llm_factory=lambda obs: ScriptedLLM(MEMBER_SAVINGS_BALANCE, obs),
            policy=policy,
            capability_id="member_savings_balance",
            app_id="meridian-core",
            tenant="alpha",
            runs_dir=RUNS,
            trace=False,
        )
        assert res.status == "success" and res.capability, res.summary
        bundle(
            "discovery-offline-scripted",
            res.evidence_dir,
            {
                "note": "SCRIPTED decisions (ScriptedLLM), not a model run. The real LLM discovery evidence lives in evidence/discovery/.",
                "status": res.status,
                "actions": res.steps,
            },
        )

        # Use the committed (model-recorded, approved) capability if present; else the offline one.
        cap_path = catalog.path("member_savings_balance")
        if cap_path.exists():
            cap = catalog.load("member_savings_balance")
            print(
                f"using committed capability {cap.id}@{cap.version} ({cap.review.status}, recorded by {cap.provenance.model})"
            )
        else:
            catalog.save(res.capability)
            cap = catalog.approve(
                "member_savings_balance",
                "saivineeth147",
                "offline placeholder; re-record with `make discover`",
            )
            print("no committed capability; saved the offline one as a placeholder")
        cap = (
            cap.model_copy(update={"review": cap.review.model_copy(update={"status": "approved"})})
            if cap.review.status != "approved"
            else cap
        )

        def replay(name: str, params: dict[str, Any], fault: str | None = None, **kw: Any) -> None:
            print(name)
            if fault:
                httpx.post(f"{base}/__sim/faults/{fault}", timeout=5).raise_for_status()
            r = run_replay(cap, {**creds, **params}, policy, runs_dir=RUNS, trace=False, **kw)
            bundle(
                name,
                r.evidence_dir,
                {
                    "fault_injected": fault,
                    "status": r.status,
                    "outputs": r.outputs,
                    "outcome_code": r.outcome_code,
                    "failure": r.failure.model_dump() if r.failure else None,
                    "handoff": r.handoff.model_dump() if r.handoff else None,
                },
            )

        replay("replay-success", {"member_id": "100235"})
        replay("replay-business-outcome-not-found", {"member_id": "999999"})
        replay("replay-invalid-input", {"member_id": "12"})
        replay("replay-hard-failure-app-error", {"member_id": "100234"}, fault="app_error")
        replay("replay-recovered-session-expired", {"member_id": "100234"}, fault="session_expired")
        replay("replay-recovered-slow-load", {"member_id": "100234"}, fault="slow")
        bridge = OperatorBridge()
        op = ScriptedOperator(
            bridge,
            [
                {"op": "observe"},
                {"op": "click", "find": {"role": "button", "name": "OK"}},
                {"op": "fill", "find": {"name_attr": "member_no"}, "text": "100234"},
                {"op": "resume"},
            ],
            operator="jane.operator",
        ).start()
        replay(
            "replay-escalated-handoff-interstitial",
            {"member_id": "100234"},
            fault="interstitial",
            bridge=bridge,
            attended=True,
        )
        op.join()
        replay(
            "replay-unattended-stuck-interstitial", {"member_id": "100234"}, fault="interstitial"
        )

        # cross-tenant: same artifact + override on tenant bravo
        from glovebox.schema import (
            ActionKind,
            Condition,
            ConditionKind,
            Recovery,
            Step,
            Target,
            TargetStrategy,
            TenantOverride,
        )

        cap_b = cap.model_copy(deep=True)
        if not any(o.tenant == "bravo" for o in cap_b.overrides):
            cap_b.overrides.append(
                TenantOverride(
                    tenant="bravo",
                    entry_path="/t/bravo/",
                    extra_recoveries=[
                        Recovery(
                            name="post_login_notice",
                            then="continue",
                            detect=Condition(
                                kind=ConditionKind.TEXT_VISIBLE,
                                value="Scheduled maintenance",
                                timeout_ms=0,
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
                                                robustness="button text; tenant-specific notice",
                                            )
                                        ],
                                    ),
                                )
                            ],
                        )
                    ],
                    notes="Bayview renames 'Member No.'→'Member Number' and 'Find Member'→'Search'; locators fall through to name_attr/text.",
                )
            )
            catalog.save(cap_b) if cap_path.exists() else None
        print("replay-tenant-bravo-override")
        r = run_replay(
            cap_b,
            {**creds, "member_id": "100234"},
            policy,
            runs_dir=RUNS,
            tenant="bravo",
            trace=False,
        )
        bundle(
            "replay-tenant-bravo-override",
            r.evidence_dir,
            {
                "status": r.status,
                "outputs": r.outputs,
                "strategies_used": {s.step_id: s.strategy_used for s in r.steps},
            },
        )

    (EVIDENCE / "README.md").write_text(EVIDENCE_README)
    print("done")


EVIDENCE_README = """# Evidence

Every directory is one run: `events.jsonl` (structured, redacted log), `screenshots/`,
`snapshots/` (frame HTML on failure/handoff), `result.json` (replay) or `transcript.json` +
`capability.json` (discovery). Replay bundles also carry `SUMMARY.json` — what was injected and
what came back.

| Bundle | What it shows |
|---|---|
| `discovery/` | **The real LLM-driven discovery run** (Claude Sonnet 5, reached through OpenRouter's
OpenAI-compatible endpoint — see `provenance.model` in `capability.json`) that recorded `capabilities/member_savings_balance.json`. |
| `discovery-offline-scripted/` | The same loop driven by `ScriptedLLM` — no model. Shows the artifact-generation path is model-independent. Clearly not a model run. |
| `replay-success/` | Deterministic replay with a *different* member id; outputs returned. |
| `replay-business-outcome-not-found/` | Unknown member → `business_outcome: MEMBER_NOT_FOUND`, not a failure. |
| `replay-invalid-input/` | Parameter fails its pattern → `failed/input_invalid` before the app is touched. |
| `replay-hard-failure-app-error/` | Injected HTTP 500 → `failed/failure_signal` with screenshot + DOM snapshots. |
| `replay-recovered-session-expired/` | Injected session expiry → declared recovery restarts the flow → success. |
| `replay-recovered-slow-load/` | Injected 4 s delay → absorbed by load-state waits → success. |
| `replay-escalated-handoff-interstitial/` | Undeclared modal → automation stuck → **human takes over the live session** via the operator bridge, clicks OK, hands back → success. See `control.*` events. |
| `replay-unattended-stuck-interstitial/` | Same modal with no human reachable → `failed/target_not_found` with expected/observed and evidence. |
| `replay-tenant-bravo-override/` | Artifact recorded on tenant *alpha* replayed on tenant *bravo* (renamed labels, extra notice) through a `TenantOverride`. |

Regenerate the replay bundles with `make evidence`; regenerate `discovery/` with `make discover`.
"""

if __name__ == "__main__":
    main()

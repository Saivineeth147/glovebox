"""Measure a capability's resilience by redesigning the app underneath it.

REPORT §2 argues that several ordered locator strategies per target beat one "best" locator,
because which locator survives a change is unknowable at record time. That is an argument.
This turns it into a measurement: mutate the rendered page the way a redesign would, replay
the same approved capability against each mutation, and report both how many survived and
*which rung of the ladder caught the fall*.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DRIFT_ENDPOINT = "/__sim/drift"


@dataclass(frozen=True)
class DriftResult:
    """One mutation, and what replaying the capability under it produced."""

    drift: str
    survived: bool
    failure_class: str | None
    failed_step: str | None
    strategies: dict[str, str]


def strategies_used(result: Any) -> dict[str, str]:
    """Which locator strategy resolved each step that needed one.

    Steps without a target (navigate, assert on the whole page) are left out: they say
    nothing about the ladder and would dilute the attribution.
    """
    return {
        step.step_id: step.strategy_used
        for step in result.steps
        if getattr(step, "strategy_used", None)
    }


def rescues(baseline: dict[str, str], drifted: dict[str, str]) -> list[tuple[str, str, str]]:
    """Steps that resolved through a different strategy once the page changed.

    This is the evidence the ladder is doing work: the step still resolved, but a lower rung
    caught it. A step missing from either side is skipped — it failed rather than fell back.
    """
    return [
        (step_id, baseline[step_id], drifted[step_id])
        for step_id in sorted(baseline)
        if step_id in drifted and drifted[step_id] != baseline[step_id]
    ]


def survival_rate(results: Iterable[DriftResult]) -> float:
    """Fraction of mutations the capability replayed through. Zero when none were run."""
    evaluated = list(results)
    if not evaluated:
        return 0.0
    return sum(1 for r in evaluated if r.survived) / len(evaluated)


@dataclass(frozen=True)
class DriftEvalOptions:
    """Where the target lives and how the replays under evaluation should run."""

    target_url: str = "http://127.0.0.1:8089"
    tenant: str | None = None
    runs_dir: str = "runs"
    drifts: tuple[str, ...] = ()


# Frozen, so one shared instance is safe as the default and ruff is satisfied (B008).
DEFAULT_EVAL_OPTIONS = DriftEvalOptions()


def known_drifts(target_url: str) -> list[str]:
    """Ask the target which mutations it can apply, so the harness never hardcodes them."""
    import httpx

    return sorted(httpx.get(f"{target_url}{DRIFT_ENDPOINT}", timeout=10).json()["known"])


def _set_drift(target_url: str, name: str | None) -> None:
    import httpx

    httpx.request("DELETE", f"{target_url}{DRIFT_ENDPOINT}", timeout=10)
    if name is not None:
        httpx.post(f"{target_url}{DRIFT_ENDPOINT}/{name}", timeout=10).raise_for_status()


def _replay_under(drift: str | None, plan: tuple[Any, dict[str, Any], Any]) -> DriftResult:
    """Replay the capability once with `drift` armed (or nothing armed for the baseline)."""
    from glovebox.runner import run_replay

    capability, params, options = plan
    policy, replay_options = options
    _set_drift(replay_options.target_url, drift)
    result = run_replay(
        capability,
        params,
        policy,
        runs_dir=replay_options.runs_dir,
        tenant=replay_options.tenant,
        allow_draft=True,
        trace=False,
    )
    failure = result.failure
    return DriftResult(
        drift=drift or "none",
        survived=result.status == "success",
        failure_class=failure.failure_class if failure else None,
        failed_step=failure.step_id if failure else None,
        strategies=strategies_used(result),
    )


def evaluate_capability(
    capability: Any,
    params: dict[str, Any],
    policy: Any,
    options: DriftEvalOptions = DEFAULT_EVAL_OPTIONS,
) -> tuple[DriftResult, list[DriftResult]]:
    """Replay `capability` once undisturbed, then once under each mutation.

    Returns the baseline alongside the mutated runs so the caller can attribute a survival to
    the strategy that took over, which is the part worth reporting.
    """
    plan = (capability, params, (policy, options))
    names = list(options.drifts) or known_drifts(options.target_url)
    try:
        baseline = _replay_under(None, plan)
        return baseline, [_replay_under(name, plan) for name in names]
    finally:
        _set_drift(options.target_url, None)


def format_report(baseline: DriftResult, results: list[DriftResult], title: str) -> Any:
    """A table of what each redesign did, and which rung of the ladder caught the fall."""
    from rich.table import Table

    table = Table(title=title, box=None, pad_edge=False)
    for column in ("redesign", "outcome", "rescued by"):
        table.add_column(column)
    for result in results:
        moved = rescues(baseline.strategies, result.strategies)
        outcome = (
            "[green]survived[/green]"
            if result.survived
            else f"[red]{result.failure_class}[/red] at {result.failed_step}"
        )
        table.add_row(
            result.drift,
            outcome,
            ", ".join(f"{step}: {was} \u2192 {now}" for step, was, now in moved) or "\u2014",
        )
    return table

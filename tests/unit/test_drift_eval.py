"""Drift evaluation turns "the locator ladder is robust" into a number and an attribution."""

from __future__ import annotations

from glovebox.drift_eval import DriftResult, rescues, strategies_used, survival_rate


class _Step:
    def __init__(self, step_id: str, strategy: str | None) -> None:
        self.step_id = step_id
        self.strategy_used = strategy


class _Result:
    def __init__(self, steps: list[_Step]) -> None:
        self.steps = steps


def test_should_read_the_strategy_that_resolved_each_step() -> None:
    result = _Result([_Step("s01", "role_name"), _Step("s02", "table_cell")])
    assert strategies_used(result) == {"s01": "role_name", "s02": "table_cell"}


def test_should_ignore_steps_that_resolved_no_target() -> None:
    """A navigate step has no locator, so it says nothing about the ladder."""
    assert strategies_used(_Result([_Step("s01", None)])) == {}


def test_should_report_which_strategy_took_over_when_the_page_changed() -> None:
    baseline = {"s07": "css", "s08": "role_name"}
    drifted = {"s07": "table_cell", "s08": "role_name"}
    assert rescues(baseline, drifted) == [("s07", "css", "table_cell")]


def test_should_report_no_rescue_when_the_same_strategy_still_resolved() -> None:
    assert rescues({"s07": "role_name"}, {"s07": "role_name"}) == []


def test_should_compute_survival_as_a_fraction_of_mutations() -> None:
    results = [
        DriftResult("a", survived=True, failure_class=None, failed_step=None, strategies={}),
        DriftResult(
            "b", survived=False, failure_class="target_not_found", failed_step="s07", strategies={}
        ),
    ]
    assert survival_rate(results) == 0.5


def test_should_call_survival_zero_when_nothing_was_evaluated() -> None:
    assert survival_rate([]) == 0.0

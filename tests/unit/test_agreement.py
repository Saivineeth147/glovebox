"""Two independent recordings of the same goal rarely match; what they share is what holds.

Six live discovery runs of one goal produced six different artifacts on 2026-09-12. Comparing
runs is how a reviewer separates the parts that are a property of the application from the
parts that are an accident of one model sample.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glovebox.agreement import agreement, compare
from glovebox.schema.capability import Capability

ROOT = Path(__file__).resolve().parents[2]


def _artifact(**changes: Any) -> Capability:
    doc = json.loads((ROOT / "capabilities" / "member_savings_balance.json").read_text())
    doc.update(changes)
    return Capability.model_validate(doc)


def test_should_find_nothing_between_a_recording_and_itself() -> None:
    assert compare(_artifact(), _artifact()) == []
    assert agreement(_artifact(), _artifact()) == 1.0


def test_should_report_a_different_sequence_of_actions() -> None:
    base = _artifact()
    shortened = base.model_copy(update={"steps": base.steps[:-1]})
    aspects = {d.aspect for d in compare(base, shortened)}
    assert "steps" in aspects


def test_should_report_success_conditions_only_one_run_recorded() -> None:
    base = _artifact()
    extra = base.model_copy(update={"success": [*base.success, base.success[0]]})
    divergences = compare(base, extra)
    assert not divergences or all(d.aspect != "success" for d in divergences), (
        "a duplicated condition is the same set and must not read as disagreement"
    )


def test_should_report_an_outcome_only_one_run_declared() -> None:
    base = _artifact()
    without = base.model_copy(update={"outcomes": []})
    detail = next(d for d in compare(base, without) if d.aspect == "outcomes").detail
    assert "MEMBER_NOT_FOUND" in detail


def test_should_report_an_output_whose_type_changed_between_runs() -> None:
    base = _artifact()
    # Flip to whichever type the artifact does not currently declare, so this stays a real
    # divergence whatever the committed capability happens to say.
    other = "string" if str(base.outputs[0].type) == "number" else "number"
    retyped = base.model_copy(
        update={"outputs": [base.outputs[0].model_copy(update={"type": other})]}
    )
    detail = next(d for d in compare(base, retyped) if d.aspect == "outputs").detail
    assert "savings_balance" in detail


def test_should_score_full_disagreement_below_full_agreement() -> None:
    base = _artifact()
    different = base.model_copy(update={"outcomes": [], "steps": base.steps[:-1]})
    assert 0.0 <= agreement(base, different) < 1.0


def test_should_report_steps_that_resolved_through_different_locators() -> None:
    """Two runs can share every action kind and still address entirely different controls."""
    base = _artifact()
    extract_step = next(s for s in base.steps if s.extract_to)
    assert extract_step.target is not None
    retargeted = extract_step.target.model_copy(
        update={
            "strategies": [
                extract_step.target.strategies[0].model_copy(update={"kind": "bbox"}),
                *extract_step.target.strategies[1:],
            ]
        }
    )
    moved = base.model_copy(
        update={
            "steps": [
                s.model_copy(update={"target": retargeted}) if s.extract_to else s
                for s in base.steps
            ]
        }
    )
    aspects = {d.aspect for d in compare(base, moved)}
    assert "locators" in aspects

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from glovebox.schema import (
    ActionKind,
    AppRef,
    Capability,
    Condition,
    ConditionKind,
    Provenance,
    RiskClass,
    Step,
    Target,
    TargetStrategy,
    TenantOverride,
)


def _target(name: str = "Find") -> Target:
    return Target(
        description=f"button {name}",
        frame=["main"],
        strategies=[
            TargetStrategy(kind="role_name", value={"role": "button", "name": name}, robustness="x")
        ],
    )


def _cap(**over: Any) -> Capability:
    base = dict(
        id="demo",
        version="1.0.0",
        title="t",
        description="d",
        app=AppRef(app_id="app", origin="http://127.0.0.1:8089", entry_path="/t/alpha/"),
        steps=[Step(id="s1", action=ActionKind.CLICK, intent="go", target=_target())],
        success=[Condition(kind=ConditionKind.TEXT_VISIBLE, value="ok")],
        provenance=Provenance(
            discovery_run_id="r",
            recorded_at="2026-01-01T00:00:00Z",
            model="m",
            surface="s",
            transcript_sha256="0" * 64,
        ),
    )
    base.update(over)
    return Capability(**base)


def test_roundtrip_json() -> None:
    cap = _cap()
    again = Capability.model_validate_json(cap.model_dump_json())
    assert again == cap
    assert json.loads(cap.model_dump_json())["schema_version"] == "1.0"


def test_step_requires_target_and_value() -> None:
    with pytest.raises(ValidationError, match="requires a target"):
        Step(id="s", action=ActionKind.CLICK, intent="x")
    with pytest.raises(ValidationError, match="requires a value"):
        Step(id="s", action=ActionKind.FILL, intent="x", target=_target())


def test_undeclared_output_and_param_are_rejected() -> None:
    with pytest.raises(ValidationError, match="undeclared outputs"):
        _cap(
            steps=[
                Step(
                    id="s1",
                    action=ActionKind.EXTRACT,
                    intent="x",
                    target=_target(),
                    extract_to="bal",
                )
            ]
        )
    with pytest.raises(ValidationError, match="unknown input"):
        _cap(
            steps=[
                Step(
                    id="s1",
                    action=ActionKind.FILL,
                    intent="x",
                    target=_target(),
                    value="{{ params.nope }}",
                )
            ]
        )


def test_risk_must_be_declared_honestly() -> None:
    with pytest.raises(ValidationError, match="declare it honestly"):
        _cap(
            steps=[
                Step(
                    id="s1",
                    action=ActionKind.CLICK,
                    intent="x",
                    target=_target(),
                    risk=RiskClass.IRREVERSIBLE,
                )
            ]
        )
    cap = _cap(
        steps=[
            Step(
                id="s1",
                action=ActionKind.CLICK,
                intent="x",
                target=_target(),
                risk=RiskClass.IRREVERSIBLE,
            )
        ],
        max_risk=RiskClass.IRREVERSIBLE,
    )
    assert cap.max_risk == RiskClass.IRREVERSIBLE


def test_bbox_cannot_be_primary_strategy() -> None:
    with pytest.raises(ValidationError, match="bbox must be a fallback"):
        Target(
            description="x",
            strategies=[
                TargetStrategy(
                    kind="bbox", value={"x": 0, "y": 0, "role": "button"}, robustness=""
                ),
                TargetStrategy(kind="css", value={"css": "a"}, robustness=""),
            ],
        )


def test_tenant_override_is_applied_by_step_id() -> None:
    cap = _cap(
        overrides=[
            TenantOverride(
                tenant="bravo",
                origin="http://127.0.0.1:9999",
                step_targets={"s1": _target("Search")},
            )
        ]
    )
    b = cap.for_tenant("bravo")
    assert b.app.origin == "http://127.0.0.1:9999"
    overridden = b.steps[0].target
    assert overridden is not None
    assert overridden.strategies[0].value["name"] == "Search"
    assert cap.for_tenant(None) is cap
    with pytest.raises(KeyError):
        cap.for_tenant("charlie")
    with pytest.raises(ValidationError, match="unknown step"):
        _cap(overrides=[TenantOverride(tenant="b", step_values={"zzz": "1"})])


def test_json_schema_is_exportable() -> None:
    schema = Capability.model_json_schema()
    assert "steps" in schema["properties"]


def test_should_reject_a_recovery_action_that_names_an_input_nobody_declared() -> None:
    """Validating only top-level steps meant this failed during the recovery meant to save the run."""
    doc = _cap().model_dump(mode="json")
    doc["recoveries"] = [
        {
            "name": "session_expired",
            "detect": {"kind": "text_visible", "value": "Operator Sign-In"},
            "actions": [
                {
                    "id": "r01_navigate",
                    "action": "navigate",
                    "intent": "return to the entry point",
                    "value": "{{ params.nope }}",
                }
            ],
            "then": "restart_capability",
            "max_attempts": 2,
        }
    ]

    with pytest.raises(ValidationError, match="references unknown input 'nope'"):
        Capability.model_validate(doc)


def test_should_reject_a_tenant_override_value_that_names_an_undeclared_input() -> None:
    """The same gap, on the one tenant nobody replays before shipping."""
    doc = _cap().model_dump(mode="json")
    doc["overrides"] = [{"tenant": "bravo", "step_values": {"s1": "{{ params.absent }}"}}]

    with pytest.raises(ValidationError, match="references unknown input 'absent'"):
        Capability.model_validate(doc)


def test_the_published_json_schema_should_match_what_the_code_generates() -> None:
    """docs/capability.schema.json is the contract a reader trusts, and nothing guarded it.

    `verified` was added to Outcome and the committed copy was never regenerated, so the
    published contract omitted the field that decides whether a detector is trusted. No CI step
    compares them; this test is the guard.
    """
    from typer.testing import CliRunner

    from glovebox import cli

    repo_root = Path(__file__).resolve().parents[2]
    published = (repo_root / "docs" / "capability.schema.json").read_text()
    generated = CliRunner().invoke(cli.app, ["schema"]).stdout

    assert json.loads(published) == json.loads(generated), (
        "docs/capability.schema.json is stale — run `uv run glovebox schema > docs/capability.schema.json`"
    )

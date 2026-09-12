from __future__ import annotations

import pytest

from glovebox.evidence.redaction import Redactor
from glovebox.policy.guardrails import Guardrails, Verdict
from glovebox.replay.templating import InputError, render_template, validate_inputs
from glovebox.schema import ActionKind, Parameter, ParamType, Policy, RiskClass


def test_redactor_registered_secret_and_patterns():
    r = Redactor()
    r.register_secret("s3cret-pass", "password")
    out = r.text("login password=s3cret-pass token sk-ant-abcdefghijklmnop ssn 123-45-6789 card 4111 1111 1111 1111")
    assert "s3cret-pass" not in out and "sk-ant-abc" not in out and "123-45-6789" not in out and "4111" not in out
    assert "[REDACTED:password#" in out
    assert r.obj({"k": ["s3cret-pass"]}) == {"k": [r.text("s3cret-pass")]}


def _policy(**kw) -> Policy:
    base = dict(allowed_origins=["http://127.0.0.1:8089"], allowed_path_patterns=["^/t/"], denied_path_patterns=["^/__sim"])
    base.update(kw)
    return Policy(**base)


def test_guardrails_urls():
    g = Guardrails(_policy())
    assert g.check_url("http://127.0.0.1:8089/t/alpha/app/home").allowed
    assert not g.check_url("http://127.0.0.1:8089/__sim/faults").allowed
    assert not g.check_url("http://127.0.0.1:8089/admin").allowed
    assert not g.check_url("https://bank.example.com/t/x").allowed


def test_guardrails_risk_matrix():
    g = Guardrails(_policy())
    assert g.check_action(ActionKind.FILL, RiskClass.REVERSIBLE, attended=False).allowed
    assert g.check_action(ActionKind.CLICK, RiskClass.IRREVERSIBLE, attended=True).verdict == Verdict.CONFIRM
    assert g.check_action(ActionKind.CLICK, RiskClass.IRREVERSIBLE, attended=False).verdict == Verdict.BLOCK
    assert Guardrails(_policy(irreversible_policy="block")).check_action(ActionKind.CLICK, RiskClass.IRREVERSIBLE, attended=True).verdict == Verdict.BLOCK
    assert Guardrails(_policy(allowed_actions=[ActionKind.CLICK])).check_action(ActionKind.FILL, RiskClass.READ, attended=True).verdict == Verdict.BLOCK


def test_validate_inputs_and_templates():
    from tests.unit.test_schema import _cap

    cap = _cap(inputs=[
        Parameter(name="member_id", type=ParamType.STRING, description="", pattern=r"^\d{6}$"),
        Parameter(name="limit", type=ParamType.INTEGER, description="", required=False, default=5),
    ])
    assert validate_inputs(cap, {"member_id": "100234"}) == {"member_id": "100234", "limit": 5}
    assert validate_inputs(cap, {"member_id": "100234", "limit": "7"})["limit"] == 7
    with pytest.raises(InputError, match="pattern"):
        validate_inputs(cap, {"member_id": "abc"})
    with pytest.raises(InputError, match="missing required"):
        validate_inputs(cap, {})
    with pytest.raises(InputError, match="unknown parameters"):
        validate_inputs(cap, {"member_id": "100234", "x": 1})
    assert render_template("/m/{{ params.member_id }}", {"member_id": "1"}) == "/m/1"
    with pytest.raises(InputError):
        render_template("{{ params.nope }}", {})

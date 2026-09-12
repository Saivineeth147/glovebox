from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from glovebox.agent.llm import ScriptedLLM
from glovebox.agent.scripts import MEMBER_SAVINGS_BALANCE, OPEN_SUB_ACCOUNT, standard_params
from glovebox.catalog import Catalog
from glovebox.runner import run_discovery
from glovebox.schema import Capability, Parameter, ParamType, Policy
from glovebox.testing import target_app

ROOT = Path(__file__).resolve().parents[1]
FIXED_PORT = 8089  # policies/default.yaml allowlists this origin


@pytest.fixture(scope="session")
def app_url() -> Iterator[str]:
    os.environ.setdefault("GLOVEBOX_APP_USERNAME", "teller1")
    os.environ.setdefault("GLOVEBOX_APP_PASSWORD", "teller1-pass")
    with target_app(FIXED_PORT) as base:
        yield base


@pytest.fixture(scope="session")
def policy() -> Policy:
    return Policy.load(ROOT / "policies" / "default.yaml")


@pytest.fixture(scope="session")
def runs_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("runs")


@pytest.fixture(scope="session")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Catalog:
    return Catalog(tmp_path_factory.mktemp("catalog"))


def _discover(script: list[dict], app_url: str, policy: Policy, runs_dir: Path, cap_id: str, extra: list[Parameter],
              values: dict[str, str]) -> Capability:
    std = standard_params(app_url)
    res = run_discovery(
        goal=f"offline discovery for {cap_id}", entry_url=std["entry"], params={**std["values"], **values},
        param_specs=[*std["specs"], *extra], llm_factory=lambda obs: ScriptedLLM(script, obs), policy=policy,
        capability_id=cap_id, app_id="meridian-core", tenant="alpha", runs_dir=runs_dir, trace=False,
    )
    assert res.status == "success", res.summary
    assert res.capability is not None
    return res.capability


@pytest.fixture(scope="session")
def savings_capability(app_url: str, policy: Policy, runs_dir: Path, catalog: Catalog) -> Capability:
    cap = _discover(
        MEMBER_SAVINGS_BALANCE, app_url, policy, runs_dir, "member_savings_balance",
        [Parameter(name="member_id", type=ParamType.STRING, description="Member number", pattern=r"^\d{6}$")],
        {"member_id": "100234"},
    )
    catalog.save(cap)
    return catalog.approve(cap.id, "test-reviewer")


@pytest.fixture(scope="session")
def subaccount_capability(app_url: str, policy: Policy, runs_dir: Path, catalog: Catalog) -> Capability:
    from glovebox.control.session import OperatorBridge, ScriptedOperator

    std = standard_params(app_url)
    extra = [
        Parameter(name="member_id", type=ParamType.STRING, description="Member number"),
        Parameter(name="product", type=ParamType.STRING, description="Product"),
        Parameter(name="nickname", type=ParamType.STRING, description="Nickname"),
    ]
    values = {**std["values"], "member_id": "100235", "product": "Holiday Club", "nickname": "Xmas fund"}
    bridge = OperatorBridge()
    ScriptedOperator(bridge, [{"op": "approve"}]).start()  # a human approves the irreversible submit
    res = run_discovery(
        goal="open a sub-account", entry_url=std["entry"], params=values, param_specs=[*std["specs"], *extra],
        llm_factory=lambda obs: ScriptedLLM(OPEN_SUB_ACCOUNT, obs), policy=policy, capability_id="open_sub_account",
        app_id="meridian-core", tenant="alpha", runs_dir=runs_dir, bridge=bridge, trace=False,
    )
    assert res.status == "success", res.summary
    assert res.capability is not None
    catalog.save(res.capability)
    return catalog.approve(res.capability.id, "test-reviewer")


def creds() -> dict[str, str]:
    return {"username": os.environ["GLOVEBOX_APP_USERNAME"], "password": os.environ["GLOVEBOX_APP_PASSWORD"]}

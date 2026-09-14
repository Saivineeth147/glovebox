from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from glovebox.agent.llm import ScriptedLLM
from glovebox.agent.scripts import MEMBER_SAVINGS_BALANCE, OPEN_SUB_ACCOUNT, standard_params
from glovebox.catalog import Catalog
from glovebox.runner import run_discovery
from glovebox.schema import Capability, Parameter, ParamType, Policy
from glovebox.studio.seed import EMAIL_VARIABLE, PASSWORD_VARIABLE
from glovebox.testing import target_app

ROOT = Path(__file__).resolve().parents[1]
FIXED_PORT = 8089  # policies/default.yaml allowlists this origin


def _port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture(autouse=True)
def _unseeded_studio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's `.env` out of Studio's account ladder.

    Any test that invokes the CLI runs `_bootstrap_environment`, which loads the real `.env`
    straight into `os.environ` and — by design, so an exported secret wins — never takes it back
    out. A checkout whose `.env` seeds an administrator would therefore silently demote the first
    account every later test registers. Tests that want seeding set these themselves.
    """
    monkeypatch.delenv(EMAIL_VARIABLE, raising=False)
    monkeypatch.delenv(PASSWORD_VARIABLE, raising=False)


@pytest.fixture(scope="session")
def app_url() -> Iterator[str]:
    """Serve the target on the one origin the policy allowlists.

    The port is pinned rather than allocated because `policies/default.yaml` allowlists this
    exact origin, and a run on another port would be refused by the guardrails it is meant to
    exercise. That makes a port clash a setup problem, so say so plainly: left to itself the
    suite silently talks to whatever is already listening and fails much later, in tests that
    look unrelated.
    """
    if not _port_is_free(FIXED_PORT):
        pytest.exit(
            f"port {FIXED_PORT} is already in use. The policy allowlists this exact origin, so "
            "the suite cannot move. Stop any running `glovebox target serve` and retry.",
            returncode=1,
        )
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


def _discover(
    script: list[dict[str, Any]],
    app_url: str,
    policy: Policy,
    runs_dir: Path,
    cap_id: str,
    extra: list[Parameter],
    values: dict[str, str],
) -> Capability:
    std = standard_params(app_url)
    res = run_discovery(
        goal=f"offline discovery for {cap_id}",
        entry_url=std["entry"],
        params={**std["values"], **values},
        param_specs=[*std["specs"], *extra],
        llm_factory=lambda obs: ScriptedLLM(script, obs),
        policy=policy,
        capability_id=cap_id,
        app_id="meridian-core",
        tenant="alpha",
        runs_dir=runs_dir,
        trace=False,
    )
    assert res.status == "success", res.summary
    assert res.capability is not None
    return res.capability


@pytest.fixture(scope="session")
def savings_capability(
    app_url: str, policy: Policy, runs_dir: Path, catalog: Catalog
) -> Capability:
    cap = _discover(
        MEMBER_SAVINGS_BALANCE,
        app_url,
        policy,
        runs_dir,
        "member_savings_balance",
        [
            Parameter(
                name="member_id",
                type=ParamType.STRING,
                description="Member number",
                pattern=r"^\d{6}$",
            )
        ],
        {"member_id": "100234"},
    )
    catalog.save(cap)
    # The scripted flows are written by someone who knows the app, which is exactly the
    # case --accept-unverified exists for. The savings flow probes for its detector instead
    # and does not need this; the sub-account flow declares outcomes it never walks to.
    return catalog.approve(cap.id, "test-reviewer", accept_unverified=True)


@pytest.fixture(scope="session")
def subaccount_capability(
    app_url: str, policy: Policy, runs_dir: Path, catalog: Catalog
) -> Capability:
    from glovebox.control.session import OperatorBridge, ScriptedOperator

    std = standard_params(app_url)
    extra = [
        Parameter(name="member_id", type=ParamType.STRING, description="Member number"),
        Parameter(name="product", type=ParamType.STRING, description="Product"),
        Parameter(name="nickname", type=ParamType.STRING, description="Nickname"),
    ]
    values = {
        **std["values"],
        "member_id": "100235",
        "product": "Holiday Club",
        "nickname": "Xmas fund",
    }
    bridge = OperatorBridge()
    ScriptedOperator(
        bridge, [{"op": "approve"}]
    ).start()  # a human approves the irreversible submit
    res = run_discovery(
        goal="open a sub-account",
        entry_url=std["entry"],
        params=values,
        param_specs=[*std["specs"], *extra],
        llm_factory=lambda obs: ScriptedLLM(OPEN_SUB_ACCOUNT, obs),
        policy=policy,
        capability_id="open_sub_account",
        app_id="meridian-core",
        tenant="alpha",
        runs_dir=runs_dir,
        bridge=bridge,
        trace=False,
    )
    assert res.status == "success", res.summary
    assert res.capability is not None
    catalog.save(res.capability)
    return catalog.approve(res.capability.id, "test-reviewer", accept_unverified=True)


def creds() -> dict[str, str]:
    return {
        "username": os.environ["GLOVEBOX_APP_USERNAME"],
        "password": os.environ["GLOVEBOX_APP_PASSWORD"],
    }

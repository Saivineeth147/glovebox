"""Wiring: builds a surface, logger, guardrails and control session for one run.

Both CLI commands and tests go through these two functions so that discovery and replay are
exercised with identical plumbing."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glovebox.agent.llm import LLM
from glovebox.agent.loop import DiscoveryAgent, DiscoveryResult
from glovebox.control.session import ControlSession, OperatorBridge
from glovebox.evidence.logger import EvidenceLogger, RunDir, new_run_id
from glovebox.evidence.redaction import Redactor
from glovebox.policy.guardrails import Guardrails
from glovebox.replay.engine import ReplayEngine, ReplayOptions
from glovebox.schema.capability import Capability, Parameter
from glovebox.schema.policy import Policy
from glovebox.schema.results import ReplayResult
from glovebox.surface.base import Surface
from glovebox.surface.web.playwright_surface import PlaywrightSurface


@dataclass
class RunContext:
    run_id: str
    run_dir: RunDir
    logger: EvidenceLogger
    guardrails: Guardrails
    surface: Surface
    control: ControlSession


#: Builds the surface a run drives. Injectable so the same reviewed capability can be
#: replayed through another surface — the seam the artifact was designed around.
SurfaceFactory = Callable[[RunDir], Surface]


def _context(
    prefix: str,
    runs_dir: str | Path,
    policy: Policy,
    bridge: OperatorBridge | None,
    *,
    headless: bool,
    echo: bool,
    handoff_timeout_s: float,
    capability_id: str | None = None,
    goal: str | None = None,
    trace: bool = True,
    surface_factory: SurfaceFactory | None = None,
    surface: Surface | None = None,
) -> RunContext:
    run_id = new_run_id(prefix)
    run_dir = RunDir.create(runs_dir, run_id)
    redactor = Redactor(policy.redact_patterns)
    for env in ("GLOVEBOX_APP_PASSWORD", "ANTHROPIC_API_KEY"):
        redactor.register_secret(os.environ.get(env), env.lower())
    logger = EvidenceLogger(run_id, run_dir, redactor, echo=echo)
    surface = surface or (
        surface_factory(run_dir)
        if surface_factory
        else PlaywrightSurface(run_dir, headless=headless, trace=trace)
    )
    control = ControlSession(
        run_id,
        surface,
        logger,
        bridge,
        handoff_timeout_s=handoff_timeout_s,
        capability_id=capability_id,
        goal=goal,
    )
    return RunContext(run_id, run_dir, logger, Guardrails(policy), surface, control)


def run_replay(
    capability: Capability,
    params: dict[str, Any],
    policy: Policy,
    *,
    runs_dir: str | Path = "runs",
    tenant: str | None = None,
    bridge: OperatorBridge | None = None,
    attended: bool = False,
    allow_draft: bool = False,
    headless: bool = True,
    echo: bool = False,
    handoff_timeout_s: float = 300.0,
    trace: bool = True,
    on_context: Callable[[RunContext], None] | None = None,
    on_start: Callable[[str, Path], None] | None = None,
    surface_factory: SurfaceFactory | None = None,
    repair: Any = None,
    surface: Surface | None = None,
    start_at: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ReplayResult:
    ctx = _context(
        "replay",
        runs_dir,
        policy,
        bridge,
        headless=headless,
        echo=echo,
        handoff_timeout_s=handoff_timeout_s,
        capability_id=capability.id,
        goal=capability.title,
        trace=trace,
        surface_factory=surface_factory,
        surface=surface,
    )
    if on_context:
        on_context(ctx)
    if on_start:
        on_start(ctx.run_id, ctx.run_dir.root)
    try:
        engine = ReplayEngine(
            capability,
            params,
            ctx.surface,
            ctx.guardrails,
            ctx.logger,
            ctx.control,
            ReplayOptions(
                attended=attended,
                allow_draft=allow_draft,
                repair=repair,
                start_at=start_at,
                should_cancel=should_cancel,
            ),
            tenant=tenant,
        )
        return engine.run()
    finally:
        # A surface handed in belongs to the caller: closing it would throw away the very
        # session they are keeping warm across runs.
        if surface is None:
            ctx.surface.close()


def run_discovery(
    *,
    goal: str,
    entry_url: str,
    params: dict[str, Any],
    param_specs: list[Parameter],
    llm_factory: Callable[[Callable[[], Any]], LLM],
    policy: Policy,
    capability_id: str,
    app_id: str,
    tenant: str | None,
    runs_dir: str | Path = "runs",
    bridge: OperatorBridge | None = None,
    headless: bool = True,
    echo: bool = False,
    handoff_timeout_s: float = 300.0,
    max_steps: int | None = None,
    screenshots: bool = True,
    trace: bool = True,
    on_start: Callable[[str, Path], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> DiscoveryResult:
    ctx = _context(
        "discovery",
        runs_dir,
        policy,
        bridge,
        headless=headless,
        echo=echo,
        handoff_timeout_s=handoff_timeout_s,
        capability_id=capability_id,
        goal=goal,
        trace=trace,
    )
    if on_start:
        on_start(ctx.run_id, ctx.run_dir.root)
    agent_holder: dict[str, DiscoveryAgent] = {}
    llm = llm_factory(lambda: agent_holder["agent"].last_obs if "agent" in agent_holder else None)
    try:
        agent = DiscoveryAgent(
            goal=goal,
            entry_url=entry_url,
            params=params,
            param_specs=param_specs,
            llm=llm,
            surface=ctx.surface,
            guardrails=ctx.guardrails,
            logger=ctx.logger,
            control=ctx.control,
            capability_id=capability_id,
            app_id=app_id,
            tenant=tenant,
            max_steps=max_steps or policy.max_steps,
            timeout_s=policy.run_timeout_s,
            should_cancel=should_cancel,
            screenshots=screenshots,
        )
        agent_holder["agent"] = agent
        return agent.run()
    finally:
        ctx.surface.close()

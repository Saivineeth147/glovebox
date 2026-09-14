"""Control-transfer model for human-in-the-loop handoff (Glovebox-Design-Writeup.md §5).

Exactly one party owns the live session at any time:

    AUTOMATION ──request_intervention──▶ HUMAN ──resume/complete/abort──▶ AUTOMATION
                                          │
                                          └── timeout ──▶ AUTOMATION (escalated, timed_out)

Ownership is a lease held by `ControlSession`; every transition is an event in the run log.
While HUMAN owns the session the automation thread does not act — it *services* the human:
the operator's commands (click/fill/navigate/observe) are executed on the same Playwright
page, on the automation thread, via `OperatorBridge`. That is what makes the handoff "the
same live session" rather than a fresh browser, and it keeps the sync Playwright API on one
thread. Every human action is recorded with the same target description the recorder uses,
so a reviewer can see exactly what the person did and, later, patch the capability.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from glovebox.evidence.logger import EvidenceLogger
from glovebox.schema.events import EventKind
from glovebox.surface.base import Observation, Surface, SurfaceError


class Controller(StrEnum):
    AUTOMATION = "automation"
    HUMAN = "human"


class InterventionKind(StrEnum):
    STUCK = "stuck"  # automation cannot proceed; human performs steps then resumes
    CONFIRM = "confirm"  # an irreversible step needs approval before automation performs it
    BLOCKED = "blocked"  # policy refused an action; human decides


class Intervention(BaseModel):
    id: str = Field(default_factory=lambda: f"int_{uuid.uuid4().hex[:10]}")
    run_id: str
    kind: InterventionKind
    reason: str
    observed: str | None = None
    step_id: str | None
    capability_id: str | None
    goal: str | None
    url: str
    screenshot: str | None
    observation_summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "open"  # open | resolved
    resolution: str | None = None
    operator: str | None = None
    human_actions: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class OperatorCommand:
    """What a human may do while they own the session."""

    op: str  # observe | click | fill | select | press | navigate | resume | restart | complete | abort | approve | decline
    args: dict[str, Any] = field(default_factory=dict)
    operator: str = "operator"
    reply: queue.Queue[dict[str, Any]] = field(default_factory=lambda: queue.Queue(maxsize=1))


@dataclass
class Resolution:
    action: str  # resume | restart | complete | abort | approve | decline | timed_out
    operator: str | None
    note: str | None
    human_actions: list[dict[str, Any]]


class OperatorBridge:
    """Thread-safe mailbox between operator surfaces (console, scripted) and the automation thread."""

    def __init__(self) -> None:
        self._q: queue.Queue[OperatorCommand] = queue.Queue()
        self._lock = threading.Lock()
        self.current: Intervention | None = None
        self.last_observation: Observation | None = None
        self.history: list[Intervention] = []

    def submit(
        self, op: str, operator: str = "operator", timeout: float = 30, **args: Any
    ) -> dict[str, Any]:
        cmd = OperatorCommand(op=op, args=args, operator=operator)
        self._q.put(cmd)
        try:
            return cmd.reply.get(timeout=timeout)
        except queue.Empty:
            return {"ok": False, "error": "no reply from automation thread (is a handoff open?)"}

    def request_abort(self, operator: str = "operator") -> bool:
        """Enqueue an abort without waiting for the reply. Returns whether one was waiting.

        `submit` blocks until the automation thread answers, which is right for an operator at
        the console and wrong for a stop button: a run blocked in a handoff is exactly the case
        that needs releasing, and the caller should not wait on the thread it is unblocking.
        """
        if self.current is None:
            return False
        self._q.put(OperatorCommand(op="abort", args={}, operator=operator))
        return True

    def _next(self, timeout: float) -> OperatorCommand | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for_intervention(self, timeout: float = 30) -> Intervention | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.current is not None and self.current.status == "open":
                return self.current
            time.sleep(0.05)
        return None


class ControlSession:
    def __init__(
        self,
        run_id: str,
        surface: Surface,
        logger: EvidenceLogger,
        bridge: OperatorBridge | None,
        *,
        handoff_timeout_s: float = 300.0,
        capability_id: str | None = None,
        goal: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.surface = surface
        self.logger = logger
        self.bridge = bridge
        self.handoff_timeout_s = handoff_timeout_s
        self.capability_id = capability_id
        self.goal = goal
        self.owner = Controller.AUTOMATION
        self.interventions: list[Intervention] = []

    # ------------------------------------------------------------------ transitions
    def _transfer(self, to: Controller, reason: str) -> None:
        self.logger.emit(
            EventKind.CONTROL,
            f"control {self.owner} -> {to}: {reason}",
            from_=str(self.owner),
            to=str(to),
        )
        self.owner = to

    def request_intervention(
        self,
        kind: InterventionKind,
        reason: str,
        step_id: str | None = None,
        observed: str | None = None,
    ) -> Resolution:
        """Detect-and-route + take-control + hand-back, in one blocking call on the automation thread."""
        evidence = self.surface.capture(f"handoff-{kind}")
        try:
            obs = self.surface.observe(screenshot=True, label="handoff")
            summary = obs.render_for_model(max_elements=40, max_text=1200)
            url = obs.url
        except SurfaceError as exc:
            obs, summary, url = None, f"(observation failed: {exc})", self.surface.current_url()
        intervention = Intervention(
            run_id=self.run_id,
            kind=kind,
            reason=reason,
            observed=observed,
            step_id=step_id,
            capability_id=self.capability_id,
            goal=self.goal,
            url=url,
            screenshot=evidence.get("screenshot"),
            observation_summary=summary,
        )
        self.interventions.append(intervention)
        self.logger.emit(
            EventKind.INTERVENTION,
            f"intervention {intervention.id} ({kind}): {reason}",
            step_id=step_id,
            intervention=intervention.model_dump(mode="json", exclude={"observation_summary"}),
        )
        if self.bridge is None:
            self.logger.emit(EventKind.CONTROL, "no operator channel configured; cannot hand off")
            intervention.status = "resolved"
            intervention.resolution = "timed_out"
            return Resolution("timed_out", None, "no operator channel", [])

        self._transfer(Controller.HUMAN, f"intervention {intervention.id}")
        self.bridge.current = intervention
        self.bridge.last_observation = obs
        resolution = self._serve_human(intervention)
        intervention.status = "resolved"
        intervention.resolution = resolution.action
        intervention.operator = resolution.operator
        self.bridge.current = None
        self._transfer(
            Controller.AUTOMATION, f"{resolution.action} by {resolution.operator or 'timeout'}"
        )
        self.surface.capture(f"handback-{resolution.action}")
        return resolution

    # ------------------------------------------------------------------ serving the human
    def _serve_human(self, intervention: Intervention) -> Resolution:
        assert self.bridge is not None
        deadline = time.monotonic() + self.handoff_timeout_s
        actions: list[dict[str, Any]] = []
        terminal = {"resume", "restart", "complete", "abort", "approve", "decline"}
        while time.monotonic() < deadline:
            cmd = self.bridge._next(timeout=0.25)
            if cmd is None:
                continue
            if cmd.op in terminal:
                cmd.reply.put({"ok": True, "resolution": cmd.op})
                return Resolution(cmd.op, cmd.operator, cmd.args.get("note"), actions)
            result = self._execute(cmd, intervention, actions)
            cmd.reply.put(result)
        self.logger.emit(EventKind.CONTROL, f"handoff timed out after {self.handoff_timeout_s}s")
        return Resolution("timed_out", None, "operator did not respond", actions)

    def _execute(
        self, cmd: OperatorCommand, intervention: Intervention, actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        s = self.surface
        try:
            if cmd.op == "observe":
                obs = s.observe(screenshot=True, label="operator")
                assert self.bridge is not None
                self.bridge.last_observation = obs
                return {
                    "ok": True,
                    "url": obs.url,
                    "screenshot": str(obs.screenshot),
                    "elements": [e.summary() for e in obs.elements if e.interactive],
                    "text": obs.text[:2000],
                }
            assert self.bridge is not None
            obs = self.bridge.last_observation or s.observe(label="operator")
            self.bridge.last_observation = obs
            record: dict[str, Any] = {
                "op": cmd.op,
                "operator": cmd.operator,
                "ts": datetime.now(UTC).isoformat(),
            }
            if cmd.op == "navigate":
                s.navigate(cmd.args["url"])
                record["url"] = cmd.args["url"]
            elif cmd.op in {"click", "fill", "select", "press"}:
                el = obs.element(cmd.args["ref"]) if cmd.args.get("ref") else None
                if el is not None:
                    record["target"] = s.describe_target(el).model_dump(mode="json")
                if cmd.op == "click":
                    assert el is not None
                    s.click(el)
                elif cmd.op == "fill":
                    assert el is not None
                    s.fill(el, cmd.args["text"])
                    record["value"] = cmd.args["text"]
                elif cmd.op == "select":
                    assert el is not None
                    s.select(el, cmd.args["option"])
                    record["value"] = cmd.args["option"]
                else:
                    s.press(cmd.args["key"], el)
                    record["key"] = cmd.args["key"]
            else:
                return {"ok": False, "error": f"unknown op {cmd.op}"}
            s.wait_settled("load", 200, 15000)
            actions.append(record)
            intervention.human_actions.append(record)
            self.logger.emit(
                EventKind.HUMAN_ACTION,
                f"human {cmd.op} by {cmd.operator}",
                step_id=intervention.step_id,
                **record,
            )
            obs = s.observe(screenshot=True, label="after-human")
            self.bridge.last_observation = obs
            return {"ok": True, "url": obs.url, "screenshot": str(obs.screenshot)}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class ScriptedOperator:
    """A stand-in human for tests and offline evidence. Waits for an intervention, performs the
    scripted commands on the live session through the bridge, then resolves it."""

    def __init__(
        self,
        bridge: OperatorBridge,
        commands: list[dict[str, Any]],
        operator: str = "scripted-operator",
    ) -> None:
        self.bridge = bridge
        self.commands = commands
        self.operator = operator
        self.results: list[dict[str, Any]] = []
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> ScriptedOperator:
        self._thread.start()
        return self

    def join(self, timeout: float = 60) -> None:
        self._thread.join(timeout)

    def _run(self) -> None:
        if self.bridge.wait_for_intervention(timeout=60) is None:
            return
        for c in self.commands:
            c = dict(c)
            op = c.pop("op")
            if "find" in c:
                obs = self.bridge.last_observation
                if obs is None:
                    r = self.bridge.submit("observe", self.operator)
                    self.results.append(r)
                    obs = self.bridge.last_observation
                spec = c.pop("find")
                assert obs is not None
                c["ref"] = next(
                    e.ref for e in obs.elements if all(getattr(e, k) == v for k, v in spec.items())
                )
            self.results.append(self.bridge.submit(op, self.operator, **c))

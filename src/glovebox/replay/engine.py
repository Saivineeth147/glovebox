"""Deterministic replay: the production execution path (REPORT.md §3).

No model is consulted. For each step the engine:
  1. asks policy whether the action is permitted (block → hard failure; confirm → human),
  2. resolves the target through the recorded strategies (exactly one match or stop),
  3. performs the action and waits for the surface to settle,
  4. classifies what it sees, in a fixed order:
       failure signals  →  hard failure (stop, capture evidence)
       declared outcomes →  business outcome (stop, report code)
       step expectations →  ok, else look for a recovery whose detector fires,
                            run it (bounded), then retry / continue / restart / escalate
  5. when every step is done, verifies the success conditions and returns declared outputs.

"Stuck" is a first-class state: when attended, it becomes an intervention and the engine
waits for the human; when unattended, it is a failure with evidence.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from glovebox.control.session import ControlSession, InterventionKind
from glovebox.evidence.logger import EvidenceLogger
from glovebox.policy.guardrails import Guardrails, Verdict
from glovebox.replay.extraction import extracted_value
from glovebox.replay.recovery import ReplayRecovery
from glovebox.replay.reporting import ReplayReporting
from glovebox.replay.signals import (
    _ExtractionMismatch,
    _Recover,
    _RestartAfterHuman,
    _RetryAfterHuman,
    _Stop,
)
from glovebox.schema.capability import (
    ActionKind,
    Capability,
    ReviewStatus,
    Step,
)
from glovebox.schema.events import EventKind
from glovebox.schema.results import (
    FailureClass,
    HandoffRecord,
    ReplayResult,
    StepRecord,
)
from glovebox.surface.base import Resolved, Surface, SurfaceError

from .templating import (
    InputError,
    coerce_output,
    referenced_parameters,
    render_template,
    validate_inputs,
)


@dataclass
class ReplayOptions:
    #: Begin at this step instead of the first. Set when the caller already holds an
    #: authenticated session, so the sign-in prefix does not need running again.
    start_at: str | None = None
    #: When set, a target that stops resolving gets one model call proposing a replacement
    #: locator. The proposal is written beside the evidence and never applied: healing at
    #: replay time would put a model back in the production path.
    repair: Any = None
    attended: bool = False  # a human is reachable through the control session
    allow_draft: bool = False  # bypass the approval gate (dev only)
    screenshot_each_step: bool = True
    #: Asked before each step. A thread cannot be killed from outside, so stopping a run
    #: has to be cooperative: the loop checks, finishes the step it is on, and stops.
    should_cancel: Callable[[], bool] | None = None


def steps_from(steps: list[Step], start_at: str | None) -> list[Step]:
    """The steps to run, beginning at `start_at` when one is named.

    An unknown id raises rather than running nothing: a typo would otherwise skip the whole
    flow and report success on a run that did nothing at all.
    """
    if start_at is None:
        return steps
    for index, step in enumerate(steps):
        if step.id != start_at:
            continue
        if index == 0 or steps[0].action != ActionKind.NAVIGATE:
            return steps[index:]
        # A warm session is a session, not a screen. The entry navigation is kept so the run
        # starts where the capability expects, and only the sign-in it no longer needs is
        # skipped.
        return [steps[0], *steps[index:]]
    raise ValueError(f"no step {start_at!r} in {steps[0].id}..{steps[-1].id}")


def session_prefix(capability: Capability) -> list[Step]:
    """The leading steps that exist only to establish a session.

    Found by following the credentials: the last step that substitutes a sensitive parameter,
    plus the click that submits it. This is what a session-bootstrap capability would own
    instead, and what a caller holding a warm session can skip — the write-up's §7 first cut.
    """
    sensitive = {p.name for p in capability.inputs if p.sensitive}
    if not sensitive:
        return []
    last_credential = -1
    for index, step in enumerate(capability.steps):
        if step.value and any(f"params.{name}" in step.value for name in sensitive):
            last_credential = index
    if last_credential < 0:
        return []
    for index in range(last_credential + 1, len(capability.steps)):
        if capability.steps[index].action != ActionKind.CLICK:
            continue
        end = index + 1
        # The checkpoint that follows the submit is about the sign-in having worked, so it
        # belongs to the prefix too; a resumed run has no sign-in for it to confirm.
        if end < len(capability.steps) and capability.steps[end].action == ActionKind.ASSERT:
            end += 1
        return capability.steps[:end]
    return capability.steps[: last_credential + 1]


class ReplayEngine(ReplayReporting, ReplayRecovery):
    def __init__(
        self,
        capability: Capability,
        params: dict[str, Any],
        surface: Surface,
        guardrails: Guardrails,
        logger: EvidenceLogger,
        control: ControlSession,
        options: ReplayOptions | None = None,
        tenant: str | None = None,
    ) -> None:
        self.cap = capability.for_tenant(tenant)
        self.raw_params = params
        self.surface = surface
        self.guardrails = guardrails
        self.log = logger
        self.control = control
        self.opt = options or ReplayOptions()
        self.tenant = tenant or self.cap.app.tenant
        self.run_id = logger.run_id
        self.started = datetime.now(UTC)
        self.records: list[StepRecord] = []
        self.outputs: dict[str, Any] = {}
        self.handoff: HandoffRecord | None = None
        self._restarts = 0
        self._recovery_uses: dict[str, int] = {}
        # The strategy that resolved the most recent target, kept so a failure after
        # resolution can still report which rung of the ladder was in play.
        self._last_strategy: str | None = None

    # ------------------------------------------------------------------ entry
    def run(self) -> ReplayResult:
        self.log.emit(
            EventKind.RUN_STARTED,
            f"replay {self.cap.id}@{self.cap.version} tenant={self.tenant}",
            capability=self.cap.id,
            version=self.cap.version,
            attended=self.opt.attended,
        )
        try:
            self._gate()
            params = validate_inputs(
                self.cap,
                self.raw_params,
                referenced_parameters(steps_from(self.cap.steps, self.opt.start_at)),
            )
            for p in self.cap.inputs:
                if p.sensitive and p.name in params:
                    self.log.redactor.register_secret(str(params[p.name]), p.name)
            self._params = params
            self._execute_all()
            return self._done(self._finish_success())
        except _Stop as stop:
            return self._done(stop.result)
        except InputError as exc:
            return self._done(self._fail(FailureClass.INPUT_INVALID, None, str(exc)))
        except SurfaceError as exc:
            return self._done(self._fail(FailureClass.SURFACE_ERROR, None, str(exc)))

    # ------------------------------------------------------------------ gates
    def _gate(self) -> None:
        if (
            self.guardrails.policy.require_approved_for_replay
            and self.cap.review.status != ReviewStatus.APPROVED
            and not self.opt.allow_draft
        ):
            raise _Stop(
                self._fail(
                    FailureClass.NOT_APPROVED,
                    None,
                    f"capability {self.cap.id}@{self.cap.version} is {self.cap.review.status}; "
                    "unattended replay requires an approved artifact (or --allow-draft in dev)",
                )
            )
        self.guardrails.require_url(self.cap.app.origin + "/")

    # ------------------------------------------------------------------ main loop
    def _execute_all(self) -> None:
        i = 0
        steps = steps_from(self.cap.steps, self.opt.start_at)
        while i < len(steps):
            if self.opt.should_cancel is not None and self.opt.should_cancel():
                raise _Stop(
                    self._fail(
                        FailureClass.CANCELLED,
                        steps[i].id,
                        "stopped from the console before this step ran",
                    )
                )
            step = steps[i]
            action = self._run_step(step)
            if action == "restart":
                i = 0
                continue
            i += 1

    def _run_step(self, step: Step, attempt: int = 1) -> str:
        t0 = time.monotonic()
        started = datetime.now(UTC)
        self.log.emit(
            EventKind.STEP_STARTED,
            f"{step.action} — {step.intent}",
            step_id=step.id,
            attempt=attempt,
        )
        rec = StepRecord(
            step_id=step.id, action=str(step.action), status="ok", started_at=started, duration_ms=0
        )
        try:
            self._policy(step)
            try:
                strategy = self._act(step)
            except SurfaceError as exc:
                self._propose_repair(step)
                self._stuck(
                    step,
                    rec,
                    FailureClass.SURFACE_ERROR,
                    str(exc),
                    expected=step.target.description if step.target else str(step.action),
                )
                strategy = None
            except _ExtractionMismatch as mismatch:
                # The target resolved; it was the value behind it that was wrong, so the
                # strategy that found it is still the useful thing to record.
                rec.strategy_used = self._last_strategy
                self._stuck(
                    step,
                    rec,
                    FailureClass.CHECKPOINT_FAILED,
                    str(mismatch),
                    expected=mismatch.expected,
                    observed=mismatch.observed,
                )
                strategy = self._last_strategy
            rec.strategy_used = strategy
            self.surface.wait_settled(
                step.wait.load_state, step.wait.settle_ms, step.wait.timeout_ms
            )
            self._classify_after(step, rec)
            if self.opt.screenshot_each_step:
                obs = self.surface.observe(screenshot=True, label=f"after-{step.id}")
                self.log.emit(
                    EventKind.EVIDENCE,
                    f"screen after {step.id}",
                    step_id=step.id,
                    screenshot=str(obs.screenshot) if obs.screenshot else None,
                    url=obs.url,
                    title=obs.title,
                )
        except _Recover as r:
            rec.status = "recovered"
            rec.recoveries.append(r.recovery.name)
            self._record(rec, t0)
            return self._apply_recovery(step, r.recovery, attempt)
        except _RetryAfterHuman:
            rec.status = "recovered"
            rec.recoveries.append("human")
            self._record(rec, t0)
            if attempt >= 3:
                raise _Stop(
                    self._fail(
                        FailureClass.CHECKPOINT_FAILED,
                        step.id,
                        "still failing after human intervention",
                    )
                ) from None
            return self._run_step(step, attempt + 1)
        except _RestartAfterHuman:
            rec.status = "recovered"
            rec.recoveries.append("human:restart")
            self._record(rec, t0)
            self._restarts += 1
            if self._restarts > 2:
                raise _Stop(
                    self._fail(FailureClass.RECOVERY_EXHAUSTED, step.id, "too many restarts")
                ) from None
            return "restart"
        except _Stop:
            rec.status = "failed"
            self._record(rec, t0)
            raise
        self._record(rec, t0)
        return "next"

    def _record(self, rec: StepRecord, t0: float) -> None:
        rec.duration_ms = int((time.monotonic() - t0) * 1000)
        self.records.append(rec)
        self.log.emit(
            EventKind.STEP_FINISHED,
            f"{rec.status} in {rec.duration_ms}ms via {rec.strategy_used or '-'}",
            step_id=rec.step_id,
            status=rec.status,
            recoveries=rec.recoveries,
        )

    # ------------------------------------------------------------------ policy
    def _policy(self, step: Step) -> None:
        d = self.guardrails.check_action(step.action, step.risk, attended=self.opt.attended)
        self.log.emit(
            EventKind.POLICY_DECISION,
            f"{d.verdict}: {d.reason}",
            step_id=step.id,
            risk=str(step.risk),
        )
        if d.verdict == Verdict.BLOCK:
            raise _Stop(self._fail(FailureClass.POLICY_VIOLATION, step.id, d.reason))
        if d.verdict == Verdict.CONFIRM:
            res = self.control.request_intervention(
                InterventionKind.CONFIRM,
                f"irreversible step needs approval: {step.intent}",
                step.id,
            )
            self._note_handoff(res, step.id)
            if res.action != "approve":
                raise _Stop(
                    self._escalated(step.id, f"operator {res.action} the irreversible step")
                )
        if step.action == ActionKind.NAVIGATE:
            url = self._url(step)
            d = self.guardrails.check_url(url)
            if not d.allowed:
                raise _Stop(self._fail(FailureClass.POLICY_VIOLATION, step.id, d.reason))

    # ------------------------------------------------------------------ acting
    def _url(self, step: Step) -> str:
        assert step.value is not None
        v = render_template(step.value, self._params, self.cap.app.model_dump())
        return v if v.startswith("http") else self.cap.app.origin + v

    def _act(self, step: Step) -> str | None:
        s = self.surface
        if step.action == ActionKind.NAVIGATE:
            s.navigate(self._url(step))
            return "url"
        if step.action == ActionKind.WAIT:
            return None
        if step.action == ActionKind.ASSERT:
            return None
        if step.action == ActionKind.EXPECT_DIALOG:
            assert step.dialog_response is not None
            s.arm_dialog(step.dialog_response)
            return None
        if step.action == ActionKind.PRESS:
            assert step.value is not None
            el = self._resolve(step).element if step.target else None
            s.press(step.value, el)
            return "key"
        assert step.target is not None
        resolved = self._resolve(step)
        self._last_strategy = str(resolved.strategy_kind)
        el = resolved.element
        if step.action == ActionKind.CLICK:
            s.click(el)
        elif step.action == ActionKind.FILL:
            assert step.value is not None
            s.fill(el, render_template(step.value, self._params, self.cap.app.model_dump()))
        elif step.action == ActionKind.SELECT:
            assert step.value is not None
            s.select(el, render_template(step.value, self._params, self.cap.app.model_dump()))
        elif step.action == ActionKind.EXTRACT:
            assert step.extract_to is not None
            self._extract(step, el.text if el.value is None else (el.value or el.text))
        return str(resolved.strategy_kind)

    def _resolve(self, step: Step) -> Resolved:
        assert step.target is not None
        try:
            r = self.surface.resolve(step.target)
        except SurfaceError as exc:
            self.log.emit(EventKind.TARGET_RESOLVED, f"unresolved: {exc}", step_id=step.id)
            raise SurfaceError(f"target not found: {exc}") from exc
        self.log.emit(
            EventKind.TARGET_RESOLVED,
            f"{step.target.description} via {r.strategy_kind}#{r.strategy_index}",
            step_id=step.id,
            strategy=r.strategy_kind,
            index=r.strategy_index,
        )
        return r

    def _propose_repair(self, step: Step) -> None:
        """Ask once for a replacement locator and record it for review, without applying it."""
        if self.opt.repair is None or step.target is None:
            return
        from glovebox.repair import propose_strategy

        proposal = propose_strategy(
            step.target, self.surface.observe(label=f"repair-{step.id}").elements, self.opt.repair
        )
        if proposal is None:
            return
        path = proposal.write(self.log.run_dir.root, step.id)
        self.log.emit(
            EventKind.EVIDENCE,
            f"repair proposed for {step.id}: {proposal.strategy.kind} -> "
            f"{proposal.resolved_to}. Not applied; review before it runs unattended.",
            step_id=step.id,
            proposal=path,
        )

    def _extract(self, step: Step, text: str) -> None:
        assert step.extract_to is not None
        spec = next(o for o in self.cap.outputs if o.name == step.extract_to)
        value = extracted_value(text, step.value)  # regex stored in value for extract steps
        if value is None:
            raise _ExtractionMismatch(step.extract_to, f"text matching {step.value!r}", text[:200])
        self.outputs[step.extract_to] = coerce_output(str(value), spec.type)
        if spec.sensitive:
            self.log.redactor.register_secret(str(value), step.extract_to)
        self.log.emit(
            EventKind.ACTION, f"extracted {step.extract_to}", step_id=step.id, value=str(value)
        )

    # ------------------------------------------------------------------ classification

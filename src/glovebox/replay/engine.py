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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from glovebox.control.session import ControlSession, InterventionKind
from glovebox.evidence.logger import EvidenceLogger
from glovebox.policy.guardrails import Guardrails, Verdict
from glovebox.schema.capability import (
    ActionKind,
    Capability,
    Condition,
    Recovery,
    ReviewStatus,
    Step,
)
from glovebox.schema.events import EventKind
from glovebox.schema.results import (
    Failure,
    FailureClass,
    HandoffRecord,
    ReplayResult,
    ReplayStatus,
    StepRecord,
)
from glovebox.surface.base import Surface, SurfaceError

from .templating import InputError, coerce_output, render_template, validate_inputs


@dataclass
class ReplayOptions:
    attended: bool = False  # a human is reachable through the control session
    allow_draft: bool = False  # bypass the approval gate (dev only)
    screenshot_each_step: bool = True


class _Stop(Exception):
    def __init__(self, result: ReplayResult) -> None:
        self.result = result


class ReplayEngine:
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
            params = validate_inputs(self.cap, self.raw_params)
            for p in self.cap.inputs:
                if p.sensitive and p.name in params:
                    self.log.redactor.register_secret(str(params[p.name]), p.name)
            self._params = params
            self._execute_all()
            return self._finish_success()
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
        steps = self.cap.steps
        while i < len(steps):
            step = steps[i]
            action = self._run_step(step)
            if action == "restart":
                i = 0
                continue
            i += 1

    def _run_step(self, step: Step, attempt: int = 1) -> str:
        t0 = time.monotonic()
        started = datetime.now(UTC)
        self.log.emit(EventKind.STEP_STARTED, f"{step.action} — {step.intent}", step_id=step.id, attempt=attempt)
        rec = StepRecord(step_id=step.id, action=str(step.action), status="ok", started_at=started, duration_ms=0)
        try:
            self._policy(step)
            strategy = self._act(step)
            rec.strategy_used = strategy
            self.surface.wait_settled(step.wait.load_state, step.wait.settle_ms, step.wait.timeout_ms)
            self._classify_after(step, rec)
            if self.opt.screenshot_each_step:
                self.surface.observe(screenshot=True, label=f"after-{step.id}")
        except _Recover as r:
            rec.status = "recovered"
            rec.recoveries.append(r.recovery.name)
            self._record(rec, t0)
            return self._apply_recovery(step, r.recovery, attempt)
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
        self.log.emit(EventKind.POLICY_DECISION, f"{d.verdict}: {d.reason}", step_id=step.id, risk=str(step.risk))
        if d.verdict == Verdict.BLOCK:
            raise _Stop(self._fail(FailureClass.POLICY_VIOLATION, step.id, d.reason))
        if d.verdict == Verdict.CONFIRM:
            res = self.control.request_intervention(
                InterventionKind.CONFIRM, f"irreversible step needs approval: {step.intent}", step.id
            )
            self._note_handoff(res, step.id)
            if res.action != "approve":
                raise _Stop(self._escalated(step.id, f"operator {res.action} the irreversible step"))
        if step.action == ActionKind.NAVIGATE:
            url = self._url(step)
            d = self.guardrails.check_url(url)
            if not d.allowed:
                raise _Stop(self._fail(FailureClass.POLICY_VIOLATION, step.id, d.reason))

    # ------------------------------------------------------------------ acting
    def _url(self, step: Step) -> str:
        assert step.value is not None
        v = render_template(step.value, self._params)
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
        el = resolved.element
        if step.action == ActionKind.CLICK:
            s.click(el)
        elif step.action == ActionKind.FILL:
            assert step.value is not None
            s.fill(el, render_template(step.value, self._params))
        elif step.action == ActionKind.SELECT:
            assert step.value is not None
            s.select(el, render_template(step.value, self._params))
        elif step.action == ActionKind.EXTRACT:
            assert step.extract_to is not None
            self._extract(step, el.text if el.value is None else (el.value or el.text))
        return resolved.strategy_kind

    def _resolve(self, step: Step) -> Any:
        assert step.target is not None
        try:
            r = self.surface.resolve(step.target)
        except SurfaceError as exc:
            self.log.emit(EventKind.TARGET_RESOLVED, f"unresolved: {exc}", step_id=step.id)
            # a covering interstitial or an error page is the usual cause: give recoveries a chance
            self._check_signals_and_outcomes(step)
            rec = self._matching_recovery()
            if rec is not None:
                raise _Recover(rec) from exc
            raise _Stop(
                self._fail(
                    FailureClass.TARGET_NOT_FOUND,
                    step.id,
                    str(exc),
                    expected=step.target.description,
                    observed=self._observed_summary(),
                )
            ) from exc
        self.log.emit(
            EventKind.TARGET_RESOLVED,
            f"{step.target.description} via {r.strategy_kind}#{r.strategy_index}",
            step_id=step.id,
            strategy=r.strategy_kind,
            index=r.strategy_index,
        )
        return r

    def _extract(self, step: Step, text: str) -> None:
        assert step.extract_to is not None
        spec = next(o for o in self.cap.outputs if o.name == step.extract_to)
        value: Any = text
        if step.value:  # regex stored in value for extract steps
            import re

            m = re.search(step.value, text)
            value = m.group(1) if m and m.groups() else (m.group(0) if m else text)
        self.outputs[step.extract_to] = coerce_output(str(value), spec.type)
        if spec.sensitive:
            self.log.redactor.register_secret(str(value), step.extract_to)
        self.log.emit(EventKind.ACTION, f"extracted {step.extract_to}", step_id=step.id, value=str(value))

    # ------------------------------------------------------------------ classification
    def _classify_after(self, step: Step, rec: StepRecord) -> None:
        self._check_signals_and_outcomes(step)
        failed = self._first_failed(step.expect)
        if failed is None:
            return
        cond, observed = failed
        self.log.emit(EventKind.CONDITION, f"expectation failed: {cond.describe()} ({observed})", step_id=step.id)
        recovery = self._matching_recovery()
        if recovery is not None:
            raise _Recover(recovery)
        if self.opt.attended:
            res = self.control.request_intervention(
                InterventionKind.STUCK, f"expected {cond.describe()} after '{step.intent}', saw: {observed}", step.id
            )
            self._note_handoff(res, step.id)
            if res.action == "resume":
                ok = self._first_failed(step.expect) is None
                if ok:
                    rec.note = "expectation satisfied after human intervention"
                    return
                raise _Stop(self._fail(FailureClass.CHECKPOINT_FAILED, step.id, "still failing after human resume",
                                       expected=cond.describe(), observed=self._observed_summary()))
            if res.action == "complete":
                raise _Stop(self._finish_success(human_completed=True))
            raise _Stop(self._escalated(step.id, f"operator chose {res.action}"))
        raise _Stop(
            self._fail(
                FailureClass.CHECKPOINT_FAILED,
                step.id,
                f"post-condition not met after '{step.intent}'",
                expected=cond.describe(),
                observed=observed,
            )
        )

    def _check_signals_and_outcomes(self, step: Step) -> None:
        for sig in self.cap.failure_signals:
            ok, obs = self.surface.check(sig.model_copy(update={"timeout_ms": 0}))
            if ok:
                raise _Stop(
                    self._fail(FailureClass.FAILURE_SIGNAL, step.id, f"failure signal fired: {sig.describe()}",
                               expected="no failure signal", observed=obs)
                )
        for out in self.cap.outcomes:
            ok, _ = self.surface.check(out.detect.model_copy(update={"timeout_ms": 0}))
            if ok:
                self.log.emit(EventKind.OUTCOME, f"business outcome {out.code}", step_id=step.id, code=out.code)
                raise _Stop(self._outcome(out.code, out.description))

    def _first_failed(self, conds: list[Condition]) -> tuple[Condition, str] | None:
        for c in conds:
            ok, observed = self.surface.check(c)
            self.log.emit(EventKind.CONDITION, f"{'ok' if ok else 'FAIL'} {c.describe()}", observed=observed[:300])
            if not ok:
                return c, observed
        return None

    def _matching_recovery(self) -> Recovery | None:
        for r in self.cap.recoveries:
            if self._recovery_uses.get(r.name, 0) >= r.max_attempts:
                continue
            ok, _ = self.surface.check(r.detect.model_copy(update={"timeout_ms": 0}))
            if ok:
                return r
        return None

    def _apply_recovery(self, step: Step, recovery: Recovery, attempt: int) -> str:
        self._recovery_uses[recovery.name] = self._recovery_uses.get(recovery.name, 0) + 1
        self.log.emit(
            EventKind.RECOVERY,
            f"recovery '{recovery.name}' (use {self._recovery_uses[recovery.name]}/{recovery.max_attempts}) then {recovery.then}",
            step_id=step.id,
        )
        for a in recovery.actions:
            self._act(a)
            self.surface.wait_settled(a.wait.load_state, a.wait.settle_ms, a.wait.timeout_ms)
        if recovery.then == "retry_step":
            return self._run_step(step, attempt + 1)
        if recovery.then == "continue":
            return "next"
        if recovery.then == "restart_capability":
            self._restarts += 1
            if self._restarts > 2:
                raise _Stop(self._fail(FailureClass.RECOVERY_EXHAUSTED, step.id, "too many restarts"))
            return "restart"
        res = self.control.request_intervention(InterventionKind.STUCK, f"recovery '{recovery.name}' escalates", step.id)
        self._note_handoff(res, step.id)
        if res.action == "resume":
            return self._run_step(step, attempt + 1)
        if res.action == "complete":
            raise _Stop(self._finish_success(human_completed=True))
        raise _Stop(self._escalated(step.id, f"operator chose {res.action}"))

    # ------------------------------------------------------------------ results
    def _finish_success(self, human_completed: bool = False) -> ReplayResult:
        failed = self._first_failed(self.cap.success)
        if failed is not None:
            cond, observed = failed
            for out in self.cap.outcomes:
                ok, _ = self.surface.check(out.detect.model_copy(update={"timeout_ms": 0}))
                if ok:
                    return self._outcome(out.code, out.description)
            return self._fail(FailureClass.CHECKPOINT_FAILED, None, "success condition not met",
                              expected=cond.describe(), observed=observed)
        missing = [o.name for o in self.cap.outputs if o.name not in self.outputs]
        if missing and human_completed:
            # the human finished the flow; run the extraction steps so the caller still gets outputs
            for st in self.cap.steps:
                if st.action == ActionKind.EXTRACT and st.extract_to in missing:
                    try:
                        self._act(st)
                    except SurfaceError:
                        continue
            missing = [o.name for o in self.cap.outputs if o.name not in self.outputs]
        if missing:
            return self._fail(FailureClass.CHECKPOINT_FAILED, None, f"outputs not extracted: {missing}")
        return self._result(ReplayStatus.SUCCESS)

    def _outcome(self, code: str, description: str) -> ReplayResult:
        return self._result(ReplayStatus.BUSINESS_OUTCOME, outcome_code=code, outcome_description=description)

    def _escalated(self, step_id: str | None, why: str) -> ReplayResult:
        self.log.emit(EventKind.CONTROL, f"run escalated: {why}", step_id=step_id)
        return self._result(ReplayStatus.ESCALATED)

    def _fail(self, cls: FailureClass, step_id: str | None, message: str, *, expected: str | None = None,
              observed: str | None = None) -> ReplayResult:
        evidence = self.surface.capture(f"failure-{step_id or 'run'}")
        self.log.emit(EventKind.EVIDENCE, "failure evidence captured", step_id=step_id, **evidence)
        self.log.emit(EventKind.ERROR, f"{cls}: {message}", step_id=step_id, expected=expected, observed=observed)
        return self._result(
            ReplayStatus.FAILED,
            failure=Failure(failure_class=cls, step_id=step_id, message=message, expected=expected,
                            observed=observed, evidence=evidence),
        )

    def _result(self, status: ReplayStatus, **kw: Any) -> ReplayResult:
        return ReplayResult(
            run_id=self.run_id,
            capability_id=self.cap.id,
            capability_version=self.cap.version,
            tenant=self.tenant,
            status=status,
            outputs=dict(self.outputs) if status == ReplayStatus.SUCCESS else {},
            handoff=self.handoff,
            steps=list(self.records),
            started_at=self.started,
            finished_at=datetime.now(UTC),
            evidence_dir=str(self.log.run_dir.root),
            **kw,
        )

    def _done(self, result: ReplayResult) -> ReplayResult:
        self.log.run_dir.write_json("result.json", result.model_dump(mode="json"), self.log.redactor)
        self.log.emit(EventKind.RUN_FINISHED, f"{result.status}" + (f" ({result.outcome_code})" if result.outcome_code else ""),
                      status=str(result.status), outputs=result.outputs)
        return result

    def _note_handoff(self, res: Any, step_id: str | None) -> None:
        last = self.control.interventions[-1]
        self.handoff = HandoffRecord(
            intervention_id=last.id, reason=last.reason, step_id=step_id, resolution=res.action,
            human_actions=len(res.human_actions), operator=res.operator,
        )

    def _observed_summary(self) -> str:
        try:
            obs = self.surface.observe(label="observed")
            return f"url={obs.url} title={obs.title!r} text={obs.text[:300]!r}"
        except SurfaceError as exc:
            return f"(unobservable: {exc})"


class _Recover(Exception):
    def __init__(self, recovery: Recovery) -> None:
        self.recovery = recovery

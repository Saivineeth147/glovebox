"""What a failing step means, and what to try before giving up on it.

Split out of `engine.py` so the file that walks the steps is not also the file that decides
whether a failure is a business outcome, a known condition with a scripted response, something
a person should look at, or the end of the run. That ordering is the substance of the error
taxonomy, and it reads better on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from glovebox.control.session import InterventionKind
from glovebox.evidence.logger import EvidenceLogger
from glovebox.replay.signals import _Recover, _RestartAfterHuman, _RetryAfterHuman, _Stop
from glovebox.schema.capability import Capability, Condition, Recovery, Step
from glovebox.schema.events import EventKind
from glovebox.schema.results import FailureClass, ReplayResult, StepRecord
from glovebox.surface.base import Surface


class ReplayRecovery:
    """Failure classification and recovery. Mixed into `ReplayEngine`, which supplies the state.

    The attributes and methods below are declared, not defined: they say what this half needs
    from the other half, so the split reads as a contract rather than an assumption.
    """

    cap: Capability
    log: EvidenceLogger
    surface: Surface
    control: Any
    opt: Any
    outputs: dict[str, Any]
    _recovery_uses: dict[str, int]
    _restarts: int

    _outcome: Callable[[str, str], ReplayResult]

    _escalated: Callable[[str | None, str], ReplayResult]

    _fail: Callable[..., ReplayResult]

    _observed_summary: Callable[[], str]

    _note_handoff: Callable[[Any, str | None], None]

    _run_step: Callable[..., str]

    _act: Callable[[Step], str | None]

    _finish_success: Callable[..., ReplayResult]

    def _classify_after(self, step: Step, rec: StepRecord) -> None:
        self._check_signals_and_outcomes(step)
        failed = self._first_failed(step.expect)
        if failed is None:
            return
        cond, observed = failed
        self.log.emit(
            EventKind.CONDITION,
            f"expectation failed: {cond.describe()} ({observed})",
            step_id=step.id,
        )
        self._stuck(
            step,
            rec,
            FailureClass.CHECKPOINT_FAILED,
            f"post-condition not met after '{step.intent}'",
            expected=cond.describe(),
            observed=observed,
        )

    def _stuck(
        self,
        step: Step,
        rec: StepRecord,
        cls: FailureClass,
        message: str,
        *,
        expected: str | None,
        observed: str | None = None,
    ) -> None:
        """The step cannot proceed. In order: failure signals / outcomes, a declared recovery,
        a human (attended), else a debuggable hard failure. Returns only if a human resolved it
        with `resume` (the caller then retries the step's expectations)."""
        self._check_signals_and_outcomes(step)
        recovery = self._matching_recovery()
        if recovery is not None:
            raise _Recover(recovery)
        observed = observed or self._observed_summary()
        if not self.opt.attended:
            raise _Stop(
                self._fail(
                    cls if cls != FailureClass.SURFACE_ERROR else FailureClass.TARGET_NOT_FOUND,
                    step.id,
                    message,
                    expected=expected,
                    observed=observed,
                )
            )
        res = self.control.request_intervention(
            InterventionKind.STUCK, f"{message} (expected {expected})", step.id, observed=observed
        )
        self._note_handoff(res, step.id)
        if res.action == "resume":
            rec.note = "human intervened; step retried"
            raise _RetryAfterHuman
        if res.action == "restart":
            rec.note = "human intervened; capability restarted"
            raise _RestartAfterHuman
        if res.action == "complete":
            raise _Stop(self._finish_success(human_completed=True))
        raise _Stop(self._escalated(step.id, f"operator chose {res.action}"))

    def _check_signals_and_outcomes(self, step: Step) -> None:
        for sig in self.cap.failure_signals:
            ok, obs = self.surface.check(sig.model_copy(update={"timeout_ms": 0}))
            if ok:
                raise _Stop(
                    self._fail(
                        FailureClass.FAILURE_SIGNAL,
                        step.id,
                        f"failure signal fired: {sig.describe()}",
                        expected="no failure signal",
                        observed=obs,
                    )
                )
        for out in self.cap.outcomes:
            ok, _ = self.surface.check(out.detect.model_copy(update={"timeout_ms": 0}))
            if ok:
                self.log.emit(
                    EventKind.OUTCOME,
                    f"business outcome {out.code}",
                    step_id=step.id,
                    code=out.code,
                )
                raise _Stop(self._outcome(out.code, out.description))

    def _first_failed(self, conds: list[Condition]) -> tuple[Condition, str] | None:
        for c in conds:
            ok, observed = self.surface.check(c)
            self.log.emit(
                EventKind.CONDITION,
                f"{'ok' if ok else 'FAIL'} {c.describe()}",
                observed=observed[:300],
            )
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
                raise _Stop(
                    self._fail(FailureClass.RECOVERY_EXHAUSTED, step.id, "too many restarts")
                )
            return "restart"
        res = self.control.request_intervention(
            InterventionKind.STUCK, f"recovery '{recovery.name}' escalates", step.id
        )
        self._note_handoff(res, step.id)
        if res.action == "resume":
            return self._run_step(step, attempt + 1)
        if res.action == "complete":
            raise _Stop(self._finish_success(human_completed=True))
        raise _Stop(self._escalated(step.id, f"operator chose {res.action}"))

    # ------------------------------------------------------------------ results

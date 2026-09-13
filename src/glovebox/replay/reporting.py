"""How a replay ends, and what the caller is told about it.

Split out of `engine.py` so the file that decides *what happens next* is not also the file that
decides *how to say what happened*. These are the terminal states of the result contract —
success, business outcome, escalation, failure — and they share the run's accumulated state, so
they stay methods on the engine through a mixin rather than becoming functions that would each
need six arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from glovebox.control.session import ControlSession
from glovebox.evidence.logger import EvidenceLogger
from glovebox.schema.capability import ActionKind, Capability, Condition, Step
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


class ReplayReporting:
    """Terminal states of a replay. Mixed into `ReplayEngine`, which supplies the state.

    The attributes and methods below are declared, not defined: they say what this half needs
    from the other half, so the split reads as a contract rather than an assumption, and typing
    them concretely keeps the engine's own types intact.
    """

    cap: Capability
    log: EvidenceLogger
    surface: Surface
    control: ControlSession
    outputs: dict[str, Any]
    records: list[StepRecord]
    handoff: HandoffRecord | None
    started: datetime
    run_id: str
    tenant: str | None

    _first_failed: Callable[[list[Condition]], tuple[Condition, str] | None]

    _act: Callable[[Step], str | None]

    def _finish_success(self, human_completed: bool = False) -> ReplayResult:
        failed = self._first_failed(self.cap.success)
        if failed is not None:
            cond, observed = failed
            for out in self.cap.outcomes:
                ok, _ = self.surface.check(out.detect.model_copy(update={"timeout_ms": 0}))
                if ok:
                    return self._outcome(out.code, out.description)
            return self._fail(
                FailureClass.CHECKPOINT_FAILED,
                None,
                "success condition not met",
                expected=cond.describe(),
                observed=observed,
            )
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
            return self._fail(
                FailureClass.CHECKPOINT_FAILED, None, f"outputs not extracted: {missing}"
            )
        return self._result(ReplayStatus.SUCCESS)

    def _outcome(self, code: str, description: str) -> ReplayResult:
        return self._result(
            ReplayStatus.BUSINESS_OUTCOME, outcome_code=code, outcome_description=description
        )

    def _escalated(self, step_id: str | None, why: str) -> ReplayResult:
        self.log.emit(EventKind.CONTROL, f"run escalated: {why}", step_id=step_id)
        return self._result(ReplayStatus.ESCALATED)

    def _fail(
        self,
        cls: FailureClass,
        step_id: str | None,
        message: str,
        *,
        expected: str | None = None,
        observed: str | None = None,
    ) -> ReplayResult:
        evidence = self.surface.capture(f"failure-{step_id or 'run'}")
        self.log.emit(EventKind.EVIDENCE, "failure evidence captured", step_id=step_id, **evidence)
        self.log.emit(
            EventKind.ERROR,
            f"{cls}: {message}",
            step_id=step_id,
            expected=expected,
            observed=observed,
        )
        return self._result(
            ReplayStatus.FAILED,
            failure=Failure(
                failure_class=cls,
                step_id=step_id,
                message=message,
                expected=expected,
                observed=observed,
                evidence=evidence,
            ),
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
        self.log.run_dir.write_json(
            "result.json", result.model_dump(mode="json"), self.log.redactor
        )
        self.log.emit(
            EventKind.RUN_FINISHED,
            f"{result.status}" + (f" ({result.outcome_code})" if result.outcome_code else ""),
            status=str(result.status),
            outputs=result.outputs,
        )
        return result

    def _note_handoff(self, res: Any, step_id: str | None) -> None:
        last = self.control.interventions[-1]
        self.handoff = HandoffRecord(
            intervention_id=last.id,
            reason=last.reason,
            step_id=step_id,
            resolution=res.action,
            human_actions=len(res.human_actions),
            operator=res.operator,
        )

    def _observed_summary(self) -> str:
        try:
            obs = self.surface.observe(label="observed")
            return f"url={obs.url} title={obs.title!r} text={obs.text[:300]!r}"
        except SurfaceError as exc:
            return f"(unobservable: {exc})"

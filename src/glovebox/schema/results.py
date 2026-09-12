"""What a replay returns to the caller. The four statuses are deliberately distinct:

* `success`          — checkpoint held; `outputs` are populated.
* `business_outcome` — a declared Outcome fired (e.g. MEMBER_NOT_FOUND). Not an error.
* `escalated`        — a human was brought in; `handoff` describes what happened.
* `failed`           — hard failure; `failure` says which step, what was expected, what was seen,
                        and where the evidence is.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReplayStatus(StrEnum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    ESCALATED = "escalated"
    FAILED = "failed"


class FailureClass(StrEnum):
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_AMBIGUOUS = "target_ambiguous"
    CHECKPOINT_FAILED = "checkpoint_failed"
    FAILURE_SIGNAL = "failure_signal"
    RECOVERY_EXHAUSTED = "recovery_exhausted"
    POLICY_VIOLATION = "policy_violation"
    INPUT_INVALID = "input_invalid"
    TIMEOUT = "timeout"
    SURFACE_ERROR = "surface_error"
    NOT_APPROVED = "not_approved"


class Failure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_class: FailureClass
    step_id: str | None
    message: str
    expected: str | None = None
    observed: str | None = None
    evidence: dict[str, str] = Field(default_factory=dict, description="name -> path")


class StepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    action: str
    status: str  # ok | recovered | failed | skipped
    started_at: datetime
    duration_ms: int
    strategy_used: str | None = None
    recoveries: list[str] = Field(default_factory=list)
    note: str | None = None


class HandoffRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intervention_id: str
    reason: str
    step_id: str | None
    resolution: str  # resumed | completed_by_human | aborted | timed_out
    human_actions: int
    operator: str | None = None


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    capability_id: str
    capability_version: str
    tenant: str | None
    status: ReplayStatus
    outputs: dict[str, Any] = Field(default_factory=dict)
    outcome_code: str | None = None
    outcome_description: str | None = None
    failure: Failure | None = None
    handoff: HandoffRecord | None = None
    steps: list[StepRecord] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime
    evidence_dir: str

    @property
    def ok(self) -> bool:
        return self.status == ReplayStatus.SUCCESS

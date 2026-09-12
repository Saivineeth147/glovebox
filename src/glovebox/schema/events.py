"""One structured event type for the whole system. Every component appends `Event`s to the
run's JSONL log through the evidence logger, which redacts before writing."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventKind(StrEnum):
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    OBSERVATION = "surface.observation"
    ACTION = "surface.action"
    MODEL_DECISION = "agent.decision"
    MODEL_USAGE = "agent.usage"
    POLICY_DECISION = "policy.decision"
    STEP_STARTED = "replay.step.started"
    STEP_FINISHED = "replay.step.finished"
    TARGET_RESOLVED = "replay.target.resolved"
    CONDITION = "replay.condition"
    RECOVERY = "replay.recovery"
    OUTCOME = "replay.outcome"
    CONTROL = "control.transition"
    INTERVENTION = "control.intervention"
    HUMAN_ACTION = "control.human_action"
    EVIDENCE = "evidence.captured"
    ERROR = "error"


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    kind: EventKind
    step_id: str | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)

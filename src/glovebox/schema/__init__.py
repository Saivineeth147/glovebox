"""Typed contracts shared by every Glovebox component.

`capability` — the artifact (what a recorded flow *is*).
`results`    — what a replay returns to the calling agent.
`events`     — the structured log line every component emits.
`policy`     — the guardrail configuration.
"""

from .capability import (
    SCHEMA_VERSION,
    ActionKind,
    AppRef,
    Capability,
    Condition,
    ConditionKind,
    Extraction,
    Outcome,
    OutputSpec,
    Parameter,
    ParamType,
    Provenance,
    Recovery,
    ReviewState,
    ReviewStatus,
    RiskClass,
    Step,
    Target,
    TargetStrategy,
    TenantOverride,
    WaitSpec,
)
from .events import Event, EventKind
from .policy import Policy
from .results import Failure, ReplayResult, ReplayStatus, StepRecord

__all__ = [
    "SCHEMA_VERSION",
    "ActionKind",
    "AppRef",
    "Capability",
    "Condition",
    "ConditionKind",
    "Event",
    "EventKind",
    "Extraction",
    "Failure",
    "Outcome",
    "OutputSpec",
    "ParamType",
    "Parameter",
    "Policy",
    "Provenance",
    "Recovery",
    "ReplayResult",
    "ReplayStatus",
    "ReviewState",
    "ReviewStatus",
    "RiskClass",
    "Step",
    "StepRecord",
    "Target",
    "TargetStrategy",
    "TenantOverride",
    "WaitSpec",
]

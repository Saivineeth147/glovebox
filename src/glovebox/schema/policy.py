"""Guardrail configuration. Loaded from YAML; enforced by `glovebox.policy`."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .capability import ActionKind, RiskClass


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    allowed_origins: list[str] = Field(
        description="Exact scheme+host[:port] values the agent may act on."
    )
    allowed_path_patterns: list[str] = Field(
        default_factory=lambda: [".*"], description="Regexes; a URL must match at least one."
    )
    denied_path_patterns: list[str] = Field(
        default_factory=list, description="Regexes; matching URLs are refused even if allowed."
    )
    allowed_actions: list[ActionKind] = Field(default_factory=lambda: list(ActionKind))
    irreversible_policy: str = Field(
        default="confirm",
        pattern=r"^(block|confirm|allow)$",
        description="What to do with IRREVERSIBLE steps: block, require human confirmation, or allow.",
    )
    max_risk_unattended: RiskClass = Field(
        default=RiskClass.REVERSIBLE,
        description="Highest risk class an unattended replay may perform without a human.",
    )
    max_steps: int = Field(default=40, ge=1)
    step_timeout_s: float = Field(default=30.0, gt=0)
    run_timeout_s: float = Field(default=600.0, gt=0)
    require_approved_for_replay: bool = True
    redact_patterns: list[str] = Field(
        default_factory=list,
        description="Extra regexes redacted from logs/artifacts in addition to built-ins.",
    )

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        with Path(path).open(encoding="utf-8") as f:
            return cls.model_validate(yaml.safe_load(f))

"""Allowlist and risk-class enforcement shared by discovery and replay.

The same `Guardrails` object sits in front of every surface action, regardless of whether
the decision came from a model or from a saved artifact — the artifact is not trusted more
than the model, because a reviewer can make mistakes too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from glovebox.schema.capability import ActionKind, RiskClass
from glovebox.schema.policy import Policy


class PolicyViolation(Exception):
    pass


class Verdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    CONFIRM = "confirm"  # allowed only with explicit human confirmation


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict == Verdict.ALLOW


class Guardrails:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self._allowed = [re.compile(p) for p in policy.allowed_path_patterns]
        self._denied = [re.compile(p) for p in policy.denied_path_patterns]

    # ------------------------------------------------------------------ URLs
    def check_url(self, url: str) -> Decision:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if parts.scheme == "about":
            return Decision(Verdict.ALLOW, "blank page")
        if origin not in self.policy.allowed_origins:
            return Decision(Verdict.BLOCK, f"origin {origin} is not in the allowlist")
        path = parts.path or "/"
        for d in self._denied:
            if d.search(path):
                return Decision(Verdict.BLOCK, f"path {path} matches denied pattern {d.pattern!r}")
        if not any(a.search(path) for a in self._allowed):
            return Decision(Verdict.BLOCK, f"path {path} matches no allowed pattern")
        return Decision(Verdict.ALLOW, "url within allowlist")

    def require_url(self, url: str) -> None:
        d = self.check_url(url)
        if not d.allowed:
            raise PolicyViolation(d.reason)

    # ------------------------------------------------------------------ actions
    def check_action(
        self, action: ActionKind, risk: RiskClass, *, attended: bool
    ) -> Decision:
        if action not in self.policy.allowed_actions:
            return Decision(Verdict.BLOCK, f"action {action} is not permitted by policy")
        if risk == RiskClass.IRREVERSIBLE:
            mode = self.policy.irreversible_policy
            if mode == "block":
                return Decision(Verdict.BLOCK, "irreversible actions are blocked by policy")
            if mode == "confirm":
                if attended:
                    return Decision(Verdict.CONFIRM, "irreversible action needs human confirmation")
                return Decision(
                    Verdict.BLOCK, "irreversible action attempted in unattended mode"
                )
        if not attended and _rank(risk) > _rank(self.policy.max_risk_unattended):
            return Decision(
                Verdict.BLOCK,
                f"risk {risk} exceeds unattended ceiling {self.policy.max_risk_unattended}",
            )
        return Decision(Verdict.ALLOW, "within policy")


def _rank(r: RiskClass) -> int:
    return {RiskClass.READ: 0, RiskClass.REVERSIBLE: 1, RiskClass.IRREVERSIBLE: 2}[r]

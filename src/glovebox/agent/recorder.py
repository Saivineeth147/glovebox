"""Turns what the agent *did* into a `Capability` — the artifact is built from surface-level
facts captured at action time (targets, frames, values), never from the model's words."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from glovebox.agent.overfit import MIN_LITERAL_LENGTH, overfit_reason
from glovebox.schema.capability import (
    ActionKind,
    AppRef,
    Capability,
    Condition,
    ConditionKind,
    Outcome,
    OutputSpec,
    Parameter,
    ParamType,
    Provenance,
    Recovery,
    RiskClass,
    Step,
    Target,
    shadowing_outcome,
)

DEFAULT_FAILURE_SIGNALS = [
    Condition(kind=ConditionKind.TEXT_VISIBLE, value="Application Error", timeout_ms=0),
    Condition(kind=ConditionKind.HTTP_STATUS, value="^5\\d\\d$", timeout_ms=0),
]


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.lower().split())


class Recorder:
    def __init__(
        self,
        *,
        capability_id: str,
        app_id: str,
        tenant: str | None,
        entry_url: str,
        params: list[Parameter],
        model_name: str,
        run_id: str,
        param_values: dict[str, Any] | None = None,
    ) -> None:
        self.capability_id = capability_id
        self.app_id = app_id
        self.tenant = tenant
        parts = urlsplit(entry_url)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.entry_path = parts.path + (f"?{parts.query}" if parts.query else "")
        self.params = params
        self.model_name = model_name
        self.run_id = run_id
        self.steps: list[Step] = []
        self.outputs: list[OutputSpec] = []
        self.outcomes: list[Outcome] = []
        self.recoveries: list[Recovery] = []
        self._n = 0
        # Values this run used or saw. Conditions built from them cannot generalize.
        # While paused the run is looking, not doing: observations still count, actions
        # are not recorded. Confirming an outcome detector needs the former, not the latter.
        self.paused = False
        self.dropped_outcomes: list[str] = []
        self._seen_text: list[str] = []
        self._literals: list[str] = [
            str(v) for v in (param_values or {}).values() if len(str(v)) >= MIN_LITERAL_LENGTH
        ]

    # ------------------------------------------------------------------ steps
    def _id(self, action: str) -> str:
        self._n += 1
        return f"s{self._n:02d}_{action}"

    def navigate(self, url: str, intent: str) -> Step:
        parts = urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if path == self.entry_path:  # the entry point is tenant-specific: keep it a template
            path = "{{ app.entry_path }}"
        return self._add(
            Step(
                id=self._id("navigate"),
                action=ActionKind.NAVIGATE,
                intent=intent,
                value=path,
                risk=RiskClass.READ,
            )
        )

    def click(self, target: Target, intent: str, risk: RiskClass) -> Step:
        return self._add(
            Step(
                id=self._id("click"),
                action=ActionKind.CLICK,
                intent=intent,
                target=target,
                risk=risk,
            )
        )

    def fill(self, target: Target, value: str, intent: str) -> Step:
        return self._add(
            Step(
                id=self._id("fill"),
                action=ActionKind.FILL,
                intent=intent,
                target=target,
                value=value,
            )
        )

    def select(self, target: Target, value: str, intent: str) -> Step:
        return self._add(
            Step(
                id=self._id("select"),
                action=ActionKind.SELECT,
                intent=intent,
                target=target,
                value=value,
            )
        )

    def press(self, key: str, target: Target | None, intent: str) -> Step:
        return self._add(
            Step(
                id=self._id("press"),
                action=ActionKind.PRESS,
                intent=intent,
                target=target,
                value=key,
            )
        )

    def expect_dialog(self, response: Literal["accept", "dismiss"], intent: str) -> Step:
        return self._add(
            Step(
                id=self._id("dialog"),
                action=ActionKind.EXPECT_DIALOG,
                intent=intent,
                dialog_response=response,
                risk=RiskClass.READ,
            )
        )

    def assert_text(self, text: str, intent: str) -> Step:
        return self._add(
            Step(
                id=self._id("assert"),
                action=ActionKind.ASSERT,
                intent=intent,
                risk=RiskClass.READ,
                expect=[Condition(kind=ConditionKind.TEXT_VISIBLE, value=text, timeout_ms=8000)],
            )
        )

    def extract(
        self, target: Target, name: str, description: str, type_: str, regex: str | None
    ) -> Step:
        if not self.paused and all(o.name != name for o in self.outputs):
            self.outputs.append(
                OutputSpec(name=name, type=ParamType(type_), description=description)
            )
        return self._add(
            Step(
                id=self._id("extract"),
                action=ActionKind.EXTRACT,
                intent=f"read {name}",
                target=target,
                extract_to=name,
                value=regex,
                risk=RiskClass.READ,
            )
        )

    def human_step(self, record: dict[str, Any]) -> Step | None:
        """Fold an action a human performed during handoff into the flow."""
        op = record["op"]
        intent = f"performed by operator {record.get('operator')} during handoff"
        if op == "navigate":
            return self.navigate(record["url"], intent)
        if "target" not in record:
            return None
        target = Target.model_validate(record["target"])
        if op == "click":
            return self.click(target, intent, RiskClass.REVERSIBLE)
        if op == "fill":
            return self.fill(target, record["value"], intent)
        if op == "select":
            return self.select(target, record["value"], intent)
        if op == "press":
            return self.press(record["key"], target, intent)
        return None

    def _add(self, step: Step) -> Step:
        if not self.paused:
            self.steps.append(step)
        return step

    def _usable_steps(self) -> list[Step]:
        """Drop extract steps superseded by a later extract to the same output.

        The model explores: it reads the wrong cell, sees the value is wrong and reads the
        right one. Replay would overwrite the first result with the second anyway, so the
        earlier step contributes nothing and can only fail — and it is usually anchored on
        record-time data, which is exactly what breaks on other inputs.
        """
        last: dict[str, int] = {}
        for index, step in enumerate(self.steps):
            if step.extract_to:
                last[step.extract_to] = index
        return [
            step
            for index, step in enumerate(self.steps)
            if not step.extract_to or last[step.extract_to] == index
        ]

    def _usable_outcomes(self, success: list[Condition]) -> list[Outcome]:
        """Drop outcomes that would fire on the success screen.

        A terminal outcome detected there ends the run before the extract steps, so the
        capability reports a business outcome and returns nothing. The model reliably
        declares the goal's own success this way, and no detector would make that valid —
        so this refuses to record it rather than erroring and looping the model.
        """
        kept: list[Outcome] = []
        for outcome in self.outcomes:
            if shadowing_outcome(success, [outcome]):
                self.dropped_outcomes.append(outcome.code)
            else:
                kept.append(outcome)
        return kept

    def note_observed_text(self, text: str) -> None:
        """Keep what the run actually saw, so an outcome detector can be checked against it.

        Runs of whitespace are collapsed on both sides of the later comparison: a legacy page
        renders one sentence across several table cells, and a detector that was genuinely on
        screen must not read as unverified because of a line break between two words.
        """
        if text:
            self._seen_text.append(_collapse_whitespace(text))

    def _verified(self, detect_text: str | None) -> bool:
        """Whether any observation in this run contained `detect_text`."""
        if not detect_text:
            return False
        needle = _collapse_whitespace(detect_text)
        return any(needle in seen for seen in self._seen_text)

    def note_observed_value(self, value: str | None) -> None:
        """Remember a value read off the screen so a condition cannot be built from it."""
        if value and len(value) >= MIN_LITERAL_LENGTH:
            self._literals.append(str(value))

    def overfit_reason(self, text: str) -> str | None:
        """Why `text` must not become a replay condition, or None when it is safe."""
        return overfit_reason(text, self._literals)

    # ------------------------------------------------------------------ contract
    def declare_outcome(self, code: str, description: str, detect_text: str) -> None:
        """Recorded even while probing: an outcome is text, not a step.

        Probing exists so the model can read the wording that identifies a state it has
        not seen, so suppressing the declaration made during a probe would discard the
        one thing the probe was for.
        """
        if all(o.code != code for o in self.outcomes):
            self.outcomes.append(
                Outcome(
                    code=code,
                    description=description,
                    detect=Condition(
                        kind=ConditionKind.TEXT_VISIBLE, value=detect_text, timeout_ms=0
                    ),
                )
            )

    def drop_outcome(self, code: str) -> bool:
        """Withdraw a declared outcome. Returns whether there was one to withdraw."""
        before = len(self.outcomes)
        self.outcomes = [o for o in self.outcomes if o.code != code]
        return len(self.outcomes) < before

    def unverified_outcomes(self) -> list[str]:
        """Codes whose detector text this run never observed."""
        return [o.code for o in self.outcomes if not self._verified(o.detect.value)]

    def declare_recovery(self, name: str, detect_text: str, dismiss: Target) -> None:
        self.recoveries.append(
            Recovery(
                name=name,
                detect=Condition(kind=ConditionKind.TEXT_VISIBLE, value=detect_text, timeout_ms=0),
                actions=[
                    Step(
                        id=f"r_{len(self.recoveries) + 1}_dismiss",
                        action=ActionKind.CLICK,
                        intent=f"dismiss {name}",
                        target=dismiss,
                    )
                ],
                then="retry_step",
            )
        )

    def build(
        self,
        *,
        title: str,
        description: str,
        success_text: list[str],
        transcript: Any,
        surface_name: str,
        param_descriptions: dict[str, str] | None = None,
    ) -> Capability:
        used = {ref for s in self.steps for ref in _refs(s.value)}
        inputs = []
        for p in self.params:
            if p.name in used:
                if param_descriptions and p.name in param_descriptions:
                    p = p.model_copy(update={"description": param_descriptions[p.name]})
                inputs.append(p)
        highest = max((s.risk for s in self.steps), key=_rank, default=RiskClass.READ)
        recoveries = [*self.recoveries, _session_expired_recovery()]
        if self.paused:
            raise RuntimeError(
                "still probing: end the probe before finishing, or the capability would be "
                "missing every step taken since it began"
            )
        success = [
            Condition(kind=ConditionKind.TEXT_VISIBLE, value=t, timeout_ms=8000)
            for t in success_text
        ]
        digest = hashlib.sha256(
            json.dumps(transcript, sort_keys=True, default=str).encode()
        ).hexdigest()
        return Capability(
            id=self.capability_id,
            version="1.0.0",
            title=title,
            description=description,
            app=AppRef(
                app_id=self.app_id,
                tenant=self.tenant,
                origin=self.origin,
                entry_path=self.entry_path,
            ),
            inputs=inputs,
            outputs=self.outputs,
            steps=self._usable_steps(),
            success=success,
            outcomes=[
                o.model_copy(update={"verified": self._verified(o.detect.value)})
                for o in self._usable_outcomes(success)
            ],
            recoveries=recoveries,
            failure_signals=list(DEFAULT_FAILURE_SIGNALS),
            max_risk=highest,
            provenance=Provenance(
                discovery_run_id=self.run_id,
                recorded_at=datetime.now(UTC),
                model=self.model_name,
                surface=surface_name,
                transcript_sha256=digest,
            ),
        )


def _session_expired_recovery() -> Recovery:
    return Recovery(
        name="session_expired",
        detect=Condition(
            kind=ConditionKind.TEXT_VISIBLE, value="session has expired", timeout_ms=0
        ),
        actions=[],
        then="restart_capability",
        max_attempts=2,
    )


def _refs(value: str | None) -> list[str]:
    import re

    return re.findall(r"\{\{\s*params\.([a-z][a-z0-9_]*)\s*\}\}", value or "")


def _rank(r: RiskClass) -> int:
    return {RiskClass.READ: 0, RiskClass.REVERSIBLE: 1, RiskClass.IRREVERSIBLE: 2}[r]

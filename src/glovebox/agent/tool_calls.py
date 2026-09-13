"""The tools the model can call, as they are actually carried out.

Split out of `loop.py` so the file that runs the conversation is not also the file that
implements every verb it can utter. One method per entry in `tools.TOOLS`, each returning what
the model sees; raising from one is how a refusal reaches it, which is the mechanism an expired
element ref, an overfit condition and an unverified outcome all travel on.

They stay methods through a mixin rather than becoming functions, because each needs the run's
surface, recorder, guardrails and log, and would otherwise take five arguments to say one thing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from glovebox.agent.recorder import Recorder
from glovebox.control.session import ControlSession
from glovebox.evidence.logger import EvidenceLogger
from glovebox.policy.guardrails import Guardrails
from glovebox.replay.extraction import extracted_value
from glovebox.schema.capability import ActionKind, Condition, ConditionKind, RiskClass
from glovebox.schema.events import EventKind
from glovebox.surface.base import Element, Observation, Surface


class _Finished(Exception):
    def __init__(self, status: str, summary: str) -> None:
        self.status, self.summary = status, summary


class DiscoveryTools:
    """Implementations of the model-facing tools. Mixed into `DiscoveryAgent`.

    Everything below is an annotation rather than a stub method. A stub with a body is a real
    class attribute and joins the MRO, where it would shadow the other half's implementation;
    an annotation states the contract to a type checker and creates nothing at runtime.
    """

    surface: Surface
    recorder: Recorder
    guardrails: Guardrails
    log: EvidenceLogger
    control: ControlSession
    params: dict[str, Any]
    last_obs: Observation | None
    screenshots: bool
    _actions: int
    _finish: dict[str, Any] | None
    _nudged_about_outcomes: bool

    _observe: Callable[[bool, str], Observation]

    _obs_content: Callable[[Observation, bool], str | list[dict[str, Any]]]

    _el: Callable[[str], Element]

    _after_action: Callable[[str], str]

    _policy: Callable[[ActionKind, RiskClass, str], None]

    _escalate_internal: Callable[[str], str]

    _value: Callable[[str | None, str | None], tuple[str, str]]

    def _t_observe(self, screenshot: bool = False) -> Any:
        obs = self._observe(screenshot, "observe")
        return self._obs_content(obs, screenshot)

    def _t_navigate(self, url: str) -> str:
        self.guardrails.require_url(url)
        self._policy(ActionKind.NAVIGATE, RiskClass.READ, f"navigate {url}")
        self.surface.navigate(url)
        self._actions += 1
        self.recorder.navigate(url, f"navigate to {url}")
        return self._after_action(f"navigated to {url}")

    def _t_click(self, ref: str, why: str, risk: str = "reversible") -> str:
        el = self._el(ref)
        r = RiskClass(risk)
        self._policy(ActionKind.CLICK, r, why)
        target = self.surface.describe_target(el)
        self.surface.click(el)
        self._actions += 1
        self.recorder.click(target, why, r)
        self.log.emit(
            EventKind.ACTION, f"click {target.description}: {why}", target=target.description
        )
        return self._after_action(f"clicked {target.description}")

    def _t_fill(self, ref: str, why: str, text: str | None = None, param: str | None = None) -> str:
        el = self._el(ref)
        value, template = self._value(text, param)
        self._policy(ActionKind.FILL, RiskClass.REVERSIBLE, why)
        target = self.surface.describe_target(el)
        self.surface.fill(el, value)
        self._actions += 1
        self.recorder.fill(target, template, why)
        self.log.emit(EventKind.ACTION, f"fill {target.description} <- {template}: {why}")
        return self._after_action(f"filled {target.description}")

    def _t_select(
        self, ref: str, why: str, option: str | None = None, param: str | None = None
    ) -> str:
        el = self._el(ref)
        value, template = self._value(option, param)
        self._policy(ActionKind.SELECT, RiskClass.REVERSIBLE, why)
        target = self.surface.describe_target(el)
        self.surface.select(el, value)
        self._actions += 1
        self.recorder.select(target, template, why)
        return self._after_action(f"selected {template} in {target.description}")

    def _t_press(self, key: str, why: str, ref: str | None = None) -> str:
        el = self._el(ref) if ref else None
        self._policy(ActionKind.PRESS, RiskClass.REVERSIBLE, why)
        target = self.surface.describe_target(el) if el else None
        self.surface.press(key, el)
        self._actions += 1
        self.recorder.press(key, target, why)
        return self._after_action(f"pressed {key}")

    def _t_expect_dialog(self, response: Literal["accept", "dismiss"], why: str) -> str:
        self.surface.arm_dialog(response)
        self.recorder.expect_dialog(response, why)
        return f"next native dialog will be {response}ed"

    def _t_assert_text(self, text: str, why: str) -> str:

        ok, observed = self.surface.check(
            Condition(kind=ConditionKind.TEXT_VISIBLE, value=text, timeout_ms=5000)
        )
        if not ok:
            raise ValueError(f"assertion failed: {text!r} is not visible ({observed})")
        self.recorder.assert_text(text, why)
        return f"checkpoint recorded: {text!r} is visible"

    def _t_extract(
        self,
        ref: str,
        output: str,
        description: str,
        type: str = "string",
        regex: str | None = None,
    ) -> str:
        el = self._el(ref)
        value = el.text if el.value is None else (el.value or el.text)
        # Validate before recording: a regex that misses here records a step that reports
        # whatever sits under the wrong element as the output.
        if regex and extracted_value(str(value), regex) is None:
            raise ValueError(
                f"regex {regex!r} does not match the text of this element ({str(value)[:80]!r}). "
                "Extract from the element that actually holds the value, or drop the regex."
            )
        target = self.surface.describe_target(el)
        self.recorder.extract(target, output, description, type, regex)
        self.recorder.note_observed_value(str(value) if value is not None else None)
        self.log.emit(EventKind.ACTION, f"extract {output} from {target.description}", value=value)
        return f"{output} = {value!r} (from {target.description})"

    def _t_begin_probe(self, why: str) -> str:
        if self.recorder.paused:
            raise ValueError("a probe is already open; call end_probe first")
        self.recorder.paused = True
        self.log.emit(EventKind.MODEL_DECISION, f"probe started: {why}")
        return "Recording paused. Nothing until end_probe becomes part of the capability."

    def _t_end_probe(self) -> str:
        if not self.recorder.paused:
            raise ValueError("no probe is open")
        self.recorder.paused = False
        self.log.emit(EventKind.MODEL_DECISION, "probe ended; recording resumed")
        return "Recording resumed."

    def _t_declare_outcome(self, code: str, description: str, detect_text: str) -> str:
        if reason := self.recorder.overfit_reason(detect_text):
            raise ValueError(f"detect_text rejected: {reason}")
        self.recorder.declare_outcome(code, description, detect_text)
        return f"outcome {code} recorded"

    def _t_drop_outcome(self, code: str) -> str:
        if not self.recorder.drop_outcome(code):
            raise ValueError(f"outcome {code} was not declared, so there is nothing to drop")
        return f"outcome {code} withdrawn"

    def _t_declare_recovery(self, name: str, detect_text: str, dismiss_ref: str) -> str:
        if self.recorder.paused:
            raise ValueError(
                "a recovery names the control that dismisses it, and that control is on "
                "this probed screen, which replay never visits. Declare it after end_probe."
            )
        el = self._el(dismiss_ref)
        self.recorder.declare_recovery(name, detect_text, self.surface.describe_target(el))
        return f"recovery {name!r} recorded"

    def _t_escalate(self, reason: str) -> str:
        self.log.emit(EventKind.CONTROL, f"model requested escalation: {reason}")
        return self._escalate_internal(reason)

    def _t_finish(
        self,
        success_text: list[str],
        summary: str,
        title: str,
        parameter_descriptions: dict[str, str] | None = None,
    ) -> str:

        if self.recorder.paused:
            raise ValueError(
                "a probe is still open: return to the screen the goal ends on and call "
                "end_probe before finishing"
            )
        unverified = self.recorder.unverified_outcomes()
        if unverified and not self._nudged_about_outcomes:
            # Once, not forever. A state may be genuinely unreachable during recording — an
            # access-denied screen needs a permission the operator does not have — so insisting
            # would forbid declaring real outcomes. Nudge, then let it through unverified and
            # leave the decision to approval, which refuses it unless a reviewer says otherwise.
            self._nudged_about_outcomes = True
            raise ValueError(
                f"outcome(s) {', '.join(unverified)} were declared with detector text this run "
                "never saw on screen, so they would never fire and replay would report a hard "
                "failure where the catalog promised a business outcome. Either use begin_probe "
                "to go and read the exact wording on that screen and end_probe back here, or "
                "call drop_outcome to withdraw the claim."
            )
        for t in success_text:
            if reason := self.recorder.overfit_reason(t):
                raise ValueError(f"success_text rejected: {reason}")
            ok, observed = self.surface.check(
                Condition(kind=ConditionKind.TEXT_VISIBLE, value=t, timeout_ms=3000)
            )
            if not ok:
                raise ValueError(
                    f"success_text {t!r} is not visible on the current screen ({observed})"
                )
        self._finish = {
            "success_text": success_text,
            "summary": summary,
            "title": title,
            "parameter_descriptions": parameter_descriptions,
        }
        raise _Finished("success", summary)

    # ------------------------------------------------------------------ helpers

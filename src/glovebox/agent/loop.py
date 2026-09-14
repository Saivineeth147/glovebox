"""The observe → decide → act loop for discovery.

The model decides; the loop *executes through the same guardrails and surface the replay
engine uses*, records every action as a Step, and stops on: finish, escalation that is not
resumed, max steps, timeout, or a no-progress dead end.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from glovebox.control.session import ControlSession, InterventionKind
from glovebox.evidence.logger import EvidenceLogger
from glovebox.policy.guardrails import Guardrails, Verdict
from glovebox.schema.capability import ActionKind, Capability, Parameter, RiskClass
from glovebox.schema.events import EventKind
from glovebox.surface.base import Element, Observation, Surface, SurfaceError

from .llm import LLM
from .recorder import Recorder
from .tool_calls import DiscoveryTools, _Finished
from .tools import SYSTEM_PROMPT, TOOLS


@dataclass
class DiscoveryResult:
    status: str  # success | escalated | failed | max_steps | timeout
    capability: Capability | None
    summary: str
    steps: int
    transcript_path: Path | None
    evidence_dir: Path


class DiscoveryAgent(DiscoveryTools):
    def __init__(
        self,
        *,
        goal: str,
        entry_url: str,
        params: dict[str, Any],
        param_specs: list[Parameter],
        llm: LLM,
        surface: Surface,
        guardrails: Guardrails,
        logger: EvidenceLogger,
        control: ControlSession,
        capability_id: str,
        app_id: str,
        tenant: str | None,
        max_steps: int = 40,
        timeout_s: float = 600.0,
        screenshots: bool = True,
    ) -> None:
        self.goal, self.entry_url = goal, entry_url
        self.params, self.param_specs = params, param_specs
        self.llm, self.surface, self.guardrails, self.log, self.control = (
            llm,
            surface,
            guardrails,
            logger,
            control,
        )
        self.max_steps, self.timeout_s, self.screenshots = max_steps, timeout_s, screenshots
        self.recorder = Recorder(
            capability_id=capability_id,
            app_id=app_id,
            tenant=tenant,
            entry_url=entry_url,
            params=param_specs,
            model_name=llm.name,
            run_id=logger.run_id,
            param_values=params,
        )
        self.messages: list[dict[str, Any]] = []
        self.last_obs: Observation | None = None
        self._fingerprints: list[str] = []
        self._finish: dict[str, Any] | None = None
        self._nudged_about_outcomes = False
        self._actions = 0

    # ------------------------------------------------------------------ run
    def run(self) -> DiscoveryResult:
        for p in self.param_specs:
            if p.sensitive and p.name in self.params:
                self.log.redactor.register_secret(str(self.params[p.name]), p.name)
        self.log.emit(
            EventKind.RUN_STARTED,
            f"discovery: {self.goal}",
            entry=self.entry_url,
            model=self.llm.name,
        )
        self.guardrails.require_url(self.entry_url)
        self.surface.navigate(self.entry_url)
        self.surface.wait_settled("load", 200, 15000)
        self.recorder.navigate(self.entry_url, "open the application entry point")
        self.messages.append({"role": "user", "content": self._task_prompt()})
        t0 = time.monotonic()
        status, summary = "failed", "loop exited unexpectedly"
        try:
            for turn_no in range(1, self.max_steps + 1):
                if time.monotonic() - t0 > self.timeout_s:
                    raise _Finished("timeout", f"run exceeded {self.timeout_s}s")
                turn = self.llm.turn(SYSTEM_PROMPT, self.messages, TOOLS)
                self.log.emit(
                    EventKind.MODEL_USAGE, f"turn {turn_no}", usage=turn.usage, model=turn.model
                )
                self.messages.append({"role": "assistant", "content": turn.content})
                if turn.text:
                    self.log.emit(EventKind.MODEL_DECISION, turn.text[:500])
                if not turn.tool_uses:
                    raise _Finished("failed", f"model stopped without finishing: {turn.text[:200]}")
                results = [self._dispatch(tu) for tu in turn.tool_uses]
                self.messages.append({"role": "user", "content": results})
            raise _Finished("max_steps", f"reached max_steps={self.max_steps} without finishing")
        except _Finished as f:
            status, summary = f.status, f.summary
        except SurfaceError as exc:
            status, summary = "failed", f"surface error: {exc}"
        transcript = self.log.run_dir.write_json(
            "transcript.json", self.messages, self.log.redactor
        )
        cap = None
        if status == "success" and self._finish:
            try:
                cap = self.recorder.build(
                    title=self._finish["title"],
                    description=self._finish["summary"],
                    success_text=self._finish["success_text"],
                    transcript=self.log.redactor.obj(self.messages),
                    surface_name=type(self.surface).__name__,
                    param_descriptions=self._finish.get("parameter_descriptions"),
                )
                for code in self.recorder.dropped_outcomes:
                    self.log.emit(
                        EventKind.ERROR,
                        f"outcome {code} not recorded: its detector matches the success screen, "
                        "so it would end replay before outputs are extracted",
                    )
                self.log.run_dir.write_json(
                    "capability.json", cap.model_dump(mode="json"), self.log.redactor
                )
            except ValidationError as exc:
                # A recorded artifact that cannot validate is a failed run, not a crashed CLI.
                cap = None
                status = "failed"
                summary = f"recorded capability is invalid: {exc.errors()[0]['msg']}"

        self.log.emit(
            EventKind.RUN_FINISHED, f"{status}: {summary}", status=status, actions=self._actions
        )
        return DiscoveryResult(
            status=status,
            capability=cap,
            summary=summary,
            steps=self._actions,
            transcript_path=transcript,
            evidence_dir=self.log.run_dir.root,
        )

    # ------------------------------------------------------------------ prompts
    def _task_prompt(self) -> str:
        lines = [
            f"GOAL: {self.goal}",
            f"ENTRY URL: {self.entry_url}",
            "INPUT PARAMETERS (use `param` when typing these):",
        ]
        for p in self.param_specs:
            shown = "<hidden: sensitive>" if p.sensitive else repr(self.params.get(p.name))
            lines.append(f"  - {p.name} ({p.type}): {p.description} = {shown}")
        lines.append("Start by calling observe.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ dispatch
    def _dispatch(self, tu: dict[str, Any]) -> dict[str, Any]:
        name, inp = tu["name"], tu.get("input", {})
        try:
            content: Any = getattr(self, f"_t_{name}")(**inp)
            is_error = False
        except _Finished:
            raise
        # re.error is not a ValueError, so a regex the model wrote that does not compile would
        # otherwise escape the loop and end the run with no transcript and no capability — the
        # most expensive possible way to learn the model mistyped a pattern.
        except (SurfaceError, KeyError, ValueError, TypeError, re.error) as exc:
            content, is_error = f"ERROR: {type(exc).__name__}: {exc}", True
            self.log.emit(EventKind.ERROR, f"tool {name} failed: {exc}", tool=name)
        block: dict[str, Any] = {"type": "tool_result", "tool_use_id": tu["id"], "content": content}
        if is_error:
            block["is_error"] = True
        return block

    def _observe(self, screenshot: bool, label: str) -> Observation:
        obs = self.surface.observe(screenshot=screenshot or self.screenshots, label=label)
        self.last_obs = obs
        self.recorder.note_observed_text(obs.text)
        fp = hashlib.sha1((obs.url + obs.text).encode()).hexdigest()  # noqa: S324 — fingerprint, not security
        self._fingerprints.append(fp)
        self.log.emit(
            EventKind.OBSERVATION,
            f"seq={obs.seq} url={obs.url} elements={len(obs.elements)}",
            screenshot=str(obs.screenshot) if obs.screenshot else None,
            url=obs.url,
            title=obs.title,
        )
        return obs

    def _obs_content(self, obs: Observation, with_image: bool) -> str | list[dict[str, Any]]:
        text = obs.render_for_model()
        if with_image and obs.screenshot:
            data = base64.b64encode(Path(obs.screenshot).read_bytes()).decode()
            return [
                {"type": "text", "text": text},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": data},
                },
            ]
        return text

    def _el(self, ref: str) -> Element:
        if self.last_obs is None:
            raise ValueError("call observe first")
        return self.last_obs.element(ref)

    def _after_action(self, what: str) -> str:
        self.surface.wait_settled("load", 200, 15000)
        obs = self._observe(False, what)
        if len(self._fingerprints) >= 5 and len(set(self._fingerprints[-5:])) == 1:
            self._escalate_internal("no progress: the last 4 actions did not change the screen")
        return f"done: {what}\n\n{obs.render_for_model()}"

    def _policy(self, action: ActionKind, risk: RiskClass, intent: str) -> None:
        d = self.guardrails.check_action(action, risk, attended=self.control.bridge is not None)
        self.log.emit(
            EventKind.POLICY_DECISION, f"{d.verdict}: {d.reason}", risk=str(risk), intent=intent
        )
        if d.verdict == Verdict.BLOCK:
            raise ValueError(f"policy blocked {action}: {d.reason}")
        if d.verdict == Verdict.CONFIRM:
            res = self.control.request_intervention(
                InterventionKind.CONFIRM, f"irreversible action requested: {intent}"
            )
            if res.action != "approve":
                raise ValueError(
                    f"operator {res.action} the irreversible action; choose another path, finish, or escalate"
                )

    def _escalate_internal(self, reason: str) -> str:
        res = self.control.request_intervention(InterventionKind.STUCK, reason)
        for rec in res.human_actions:
            self.recorder.human_step(rec)
        self._fingerprints.clear()
        if res.action == "resume":
            return f"A human operator intervened ({len(res.human_actions)} actions recorded) and handed control back. Observe and continue."
        if res.action == "complete":
            return (
                "The operator completed the flow manually; their actions were recorded as steps. "
                "Observe, extract the outputs, and call finish with the success condition."
            )
        raise _Finished("escalated", f"operator resolved escalation with '{res.action}' ({reason})")

    # ------------------------------------------------------------------ tools
    def _value(self, literal: str | None, param: str | None) -> tuple[str, str]:
        if param:
            if param not in self.params:
                raise ValueError(f"unknown parameter {param!r}; known: {sorted(self.params)}")
            return str(self.params[param]), f"{{{{ params.{param} }}}}"
        if literal is None:
            raise ValueError("provide `text`/`option` or `param`")
        for p in self.param_specs:  # auto-parameterize literals that equal a known input
            if not p.sensitive and str(self.params.get(p.name)) == literal:
                return literal, f"{{{{ params.{p.name} }}}}"
        return literal, literal

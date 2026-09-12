"""Model client boundary.

`AnthropicLLM` talks to the Claude API. `ScriptedLLM` produces the same tool-call shapes from
a script and exists for offline tests and the offline demo. The agent loop cannot tell them
apart; the *recorded artifact* is identical in structure either way, which is the point —
the model's only job is to decide, and the artifact never depends on the model.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from glovebox.surface.base import Observation

DEFAULT_MODEL = "claude-opus-5"


@dataclass
class Turn:
    """Model output in API-JSON shape (`text` and `tool_use` blocks), plus usage."""

    content: list[dict[str, Any]]
    stop_reason: str
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    @property
    def text(self) -> str:
        return "\n".join(b.get("text", "") for b in self.content if b.get("type") == "text")


class LLM(Protocol):
    name: str

    def turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Turn: ...


class AnthropicLLM:
    def __init__(self, model: str | None = None, *, effort: str = "medium") -> None:
        import anthropic

        self.model = model or os.environ.get("GLOVEBOX_MODEL", DEFAULT_MODEL)
        self.name = f"anthropic:{self.model}"
        self.effort = effort
        self._client = anthropic.Anthropic()

    def turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Turn:
        # Streaming keeps long observation turns clear of HTTP timeouts. The frozen system
        # prompt and tool list are the cache prefix; observations vary per turn.
        with self._client.beta.messages.stream(
            model=self.model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=cast(Any, messages),
            tools=cast(Any, tools),
            thinking={"type": "adaptive"},
            output_config=cast(Any, {"effort": self.effort}),
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
        content = [b.model_dump(exclude_none=True) for b in msg.content]
        usage = {
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "cache_read_input_tokens": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
        }
        return Turn(
            content=content, stop_reason=msg.stop_reason or "end_turn", usage=usage, model=msg.model
        )


# ----------------------------------------------------------------------------- scripted
ScriptStep = dict[str, Any]
"""A script step is {"tool": name, "input": {...}, optional "find": {attr: value, ...}}.
`find` selects an element from the latest observation and injects its ref as `input["ref"]`.
"""


class ScriptedLLM:
    """Deterministic stand-in for the model. Used by tests and `--offline` demos only."""

    name = "scripted"

    def __init__(
        self, script: list[ScriptStep], observation: Callable[[], Observation | None]
    ) -> None:
        self._script = list(script)
        self._observation = observation
        self._i = 0

    def turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Turn:
        if self._i >= len(self._script):
            return Turn(
                content=[{"type": "text", "text": "script exhausted"}], stop_reason="end_turn"
            )
        step = self._script[self._i]
        self._i += 1
        inp = dict(step.get("input", {}))
        if "find" in step:
            obs = self._observation()
            if obs is None:
                raise RuntimeError("script step needs an observation before acting")
            inp["ref"] = _find(obs, step["find"]).ref
        block = {
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex[:12]}",
            "name": step["tool"],
            "input": inp,
        }
        text = step.get("say", f"(scripted) {step['tool']}")
        return Turn(
            content=[{"type": "text", "text": text}, block],
            stop_reason="tool_use",
            model="scripted",
        )


def _find(obs: Observation, spec: dict[str, Any]) -> Any:
    for e in obs.elements:
        if all(getattr(e, k, None) == v if k != "frame" else e.frame == v for k, v in spec.items()):
            return e
    raise RuntimeError(f"no element matches {spec} in observation {obs.seq}")

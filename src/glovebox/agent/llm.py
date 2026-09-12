"""Model client boundary.

`AnthropicLLM` talks to the Claude API. `ScriptedLLM` produces the same tool-call shapes from
a script and exists for offline tests and the offline demo. The agent loop cannot tell them
apart; the *recorded artifact* is identical in structure either way, which is the point —
the model's only job is to decide, and the artifact never depends on the model.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from glovebox.surface.base import Observation

DEFAULT_MODEL = "claude-opus-5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.5"


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


# ----------------------------------------------------------------------------- openai-compatible
class OpenAICompatibleLLM:
    """Any OpenAI-compatible chat endpoint with tool calling — OpenRouter by default.

    The loop speaks Anthropic-shaped content blocks (`tool_use` / `tool_result`); this client
    translates both directions so the agent, recorder and evidence are provider-independent.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        provider: str = "openrouter",
    ) -> None:
        import httpx

        self.provider = provider
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL") or OPENROUTER_BASE_URL
        ).rstrip("/")
        key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY (or OPENAI_API_KEY) is not set")
        self.model = model or os.environ.get("GLOVEBOX_MODEL") or DEFAULT_OPENROUTER_MODEL
        self.name = f"{provider}:{self.model}"
        headers = {"Authorization": f"Bearer {key}"}
        if "openrouter" in self.base_url:
            headers["HTTP-Referer"] = "https://github.com/Saivineeth147/glovebox"
            headers["X-Title"] = "Glovebox"
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=180.0)

    # ---- request translation
    @staticmethod
    def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    @staticmethod
    def _messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            content = m["content"]
            if m["role"] == "assistant":
                text = (
                    "".join(b.get("text", "") for b in content if b.get("type") == "text")
                    if isinstance(content, list)
                    else str(content)
                )
                calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {
                            "name": b["name"],
                            "arguments": json.dumps(b.get("input", {})),
                        },
                    }
                    for b in (content if isinstance(content, list) else [])
                    if b.get("type") == "tool_use"
                ]
                msg: dict[str, Any] = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            images: list[dict[str, Any]] = []
            parts: list[dict[str, Any]] = []
            for b in content:
                if b.get("type") == "tool_result":
                    body = b.get("content", "")
                    if isinstance(body, list):
                        texts = [x["text"] for x in body if x.get("type") == "text"]
                        images += [x for x in body if x.get("type") == "image"]
                        body = "\n".join(texts)
                    out.append(
                        {"role": "tool", "tool_call_id": b["tool_use_id"], "content": str(body)}
                    )
                elif b.get("type") == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif b.get("type") == "image":
                    images.append(b)
            for img in (
                images
            ):  # OpenAI-style tool messages cannot carry images; attach them as a user turn
                src = img["source"]
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"},
                    }
                )
            if parts:
                out.append({"role": "user", "content": parts})
        return out

    def turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Turn:
        payload = {
            "model": self.model,
            "messages": self._messages(system, messages),
            "tools": self._tools(tools),
            "tool_choice": "auto",
            "max_tokens": 4096,
            "temperature": 0,
        }
        r = self._client.post("/chat/completions", json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"{self.provider} error {r.status_code}: {r.text[:300]}")
        data = r.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content: list[dict[str, Any]] = []
        if msg.get("content"):
            content.append({"type": "text", "text": str(msg["content"])})
        for call in msg.get("tool_calls") or []:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            content.append(
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "input": args,
                }
            )
        usage = data.get("usage") or {}
        return Turn(
            content=content,
            stop_reason="tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn",
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "cache_read_input_tokens": 0,
            },
            model=data.get("model", self.model),
        )


def make_llm(model: str | None = None, provider: str | None = None) -> LLM:
    """Pick a model client from the environment.

    GLOVEBOX_LLM_PROVIDER=anthropic|openrouter|openai (default: whichever key is present,
    Anthropic first). Model id via --model or GLOVEBOX_MODEL.
    """
    provider = (provider or os.environ.get("GLOVEBOX_LLM_PROVIDER") or "").lower()
    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("OPENROUTER_API_KEY"):
            provider = "openrouter"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            raise RuntimeError(
                "no model credentials: set ANTHROPIC_API_KEY, OPENROUTER_API_KEY or OPENAI_API_KEY "
                "(or use --offline-script)"
            )
    if provider == "anthropic":
        return AnthropicLLM(model)
    if provider == "openrouter":
        return OpenAICompatibleLLM(model, provider="openrouter", base_url=OPENROUTER_BASE_URL)
    if provider == "openai":
        return OpenAICompatibleLLM(
            model or "gpt-4.1",
            provider="openai",
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    raise RuntimeError(f"unknown provider {provider!r}")


def available_provider() -> str | None:
    for env, name in (
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("OPENROUTER_API_KEY", "openrouter"),
        ("OPENAI_API_KEY", "openai"),
    ):
        if os.environ.get(env):
            return os.environ.get("GLOVEBOX_LLM_PROVIDER") or name
    return None


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

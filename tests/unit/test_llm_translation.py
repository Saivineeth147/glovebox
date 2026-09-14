from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from glovebox.agent.llm import OpenAICompatibleLLM, make_llm
from glovebox.agent.tools import TOOLS


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatibleLLM:
    llm = OpenAICompatibleLLM("test/model", api_key="k", base_url="https://router.test/v1")
    llm._client = httpx.Client(
        base_url="https://router.test/v1", transport=httpx.MockTransport(handler)
    )
    return llm


def test_openai_compatible_translation_roundtrip() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "model": "test/model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "Filling the field.",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "fill",
                                        "arguments": json.dumps(
                                            {"ref": "e2", "param": "member_id", "why": "x"}
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 20},
            },
        )

    llm = _client(handler)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "GOAL: x"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking."},
                {
                    "type": "tool_use",
                    "id": "call_0",
                    "name": "observe",
                    "input": {"screenshot": True},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_0",
                    "content": [
                        {"type": "text", "text": "URL: http://x"},
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
                        },
                    ],
                }
            ],
        },
    ]
    turn = llm.turn("SYSTEM", messages, TOOLS)
    body = seen["body"]
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "observe"
    assert body["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call_0",
        "content": "URL: http://x",
    }
    assert body["messages"][4]["content"][0]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert (
        body["tools"][0]["type"] == "function" and body["tools"][0]["function"]["name"] == "observe"
    )
    assert turn.stop_reason == "tool_use"
    assert turn.tool_uses[0] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "fill",
        "input": {"ref": "e2", "param": "member_id", "why": "x"},
    }
    assert turn.text == "Filling the field." and turn.usage["input_tokens"] == 120


def test_openai_compatible_error_is_raised() -> None:
    llm = _client(lambda req: httpx.Response(402, text="insufficient credits"))
    try:
        llm.turn("s", [{"role": "user", "content": "x"}], TOOLS)
    except RuntimeError as exc:
        assert "402" in str(exc) and "credits" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_make_llm_picks_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GLOVEBOX_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    llm = make_llm()
    assert isinstance(llm, OpenAICompatibleLLM) and llm.name.startswith("openrouter:")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    try:
        make_llm()
    except RuntimeError as exc:
        assert "no model credentials" in str(exc)

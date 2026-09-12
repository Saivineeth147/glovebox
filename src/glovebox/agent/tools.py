"""Tool surface the model sees during discovery. Kept small on purpose: every tool maps 1:1 to
an `ActionKind` the artifact can express, so anything the model does is recordable."""

from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "observe",
        "description": "Look at the current screen: URL, frames, interactive elements with refs, visible text. "
        "Set screenshot=true when text is not enough to understand layout. Refs expire on every observe.",
        "input_schema": {
            "type": "object",
            "properties": {"screenshot": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
    },
    {
        "name": "navigate",
        "description": "Go to a URL on the allowed origin. Prefer clicking the app's own links; use this for the entry point.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "click",
        "description": "Click an element by ref. Declare risk: 'irreversible' if this commits a business change "
        "(creates a record, posts a transaction, deletes, confirms a mutation); otherwise 'reversible'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "risk": {
                    "type": "string",
                    "enum": ["reversible", "irreversible"],
                    "default": "reversible",
                },
                "why": {"type": "string", "description": "One sentence: the intent of this click."},
            },
            "required": ["ref", "why"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fill",
        "description": "Type into a field. Give EITHER `text` (a literal) OR `param` (the name of an input parameter; "
        "its value is substituted by the system and, for sensitive parameters, never shown to you).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "text": {"type": "string"},
                "param": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["ref", "why"],
            "additionalProperties": False,
        },
    },
    {
        "name": "select",
        "description": "Choose an option in a dropdown by its visible text (or `param`).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "option": {"type": "string"},
                "param": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["ref", "why"],
            "additionalProperties": False,
        },
    },
    {
        "name": "press",
        "description": "Press a keyboard key (e.g. Enter) optionally focused on a ref.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "ref": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["key", "why"],
            "additionalProperties": False,
        },
    },
    {
        "name": "expect_dialog",
        "description": "Before an action that will raise a native confirm/alert dialog, declare how it must be answered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "response": {"type": "string", "enum": ["accept", "dismiss"]},
                "why": {"type": "string"},
            },
            "required": ["response", "why"],
            "additionalProperties": False,
        },
    },
    {
        "name": "assert_text",
        "description": "Checkpoint: assert that text is visible now. Use after navigations so replay can verify it "
        "reached the same screen. Fails (and tells you) if the text is not visible.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "why": {"type": "string"}},
            "required": ["text", "why"],
            "additionalProperties": False,
        },
    },
    {
        "name": "extract",
        "description": "Read an element's text into a named output the caller will receive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "output": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                "description": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["string", "number", "integer", "boolean"],
                    "default": "string",
                },
                "regex": {
                    "type": "string",
                    "description": "Optional regex; capture group 1 is the value.",
                },
            },
            "required": ["ref", "output", "description"],
            "additionalProperties": False,
        },
    },
    {
        "name": "declare_outcome",
        "description": "Declare a legitimate non-success business outcome the app can show for this flow "
        "(e.g. MEMBER_NOT_FOUND when the search finds nothing), identified by text visible in that state. "
        "Call this for outcomes you can infer from the UI even if you did not hit them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]*$"},
                "description": {"type": "string"},
                "detect_text": {"type": "string"},
            },
            "required": ["code", "description", "detect_text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "declare_recovery",
        "description": "Declare a known interstitial/exceptional state and how to clear it: text that identifies it "
        "and the ref of the control that dismisses it. Use when you had to dismiss something incidental.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "detect_text": {"type": "string"},
                "dismiss_ref": {"type": "string"},
            },
            "required": ["name", "detect_text", "dismiss_ref"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate",
        "description": "You are stuck or the next step needs a human decision. A human operator takes over the live "
        "session and hands it back; you will then get a fresh observation.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish",
        "description": "The goal is met. Provide the success condition (text visible on the final screen) and a summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "success_text": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "summary": {"type": "string"},
                "title": {"type": "string", "description": "Short capability title."},
            },
            "required": ["success_text", "summary", "title"],
            "additionalProperties": False,
        },
    },
]

SYSTEM_PROMPT = """You are Glovebox's discovery agent: an expert back-office operator working inside a legacy
bank application through a controlled automation layer. Your job is to accomplish ONE goal by
operating the real UI, while producing a clean trace that will be turned into a deterministic,
replayable capability (no model in the loop on replay).

How to work
- Always `observe` before acting; element refs are only valid for the latest observation.
- Take the shortest sensible path a trained operator would take. Do not explore.
- After every navigation or submit, `assert_text` a distinctive piece of text on the new screen.
  These checkpoints are what make replay verifiable.
- Never type literal values that come from input parameters — use `param` so the recording is
  parameterized. Sensitive parameters (credentials) are substituted for you; you never see them.
- Declare `risk: "irreversible"` on clicks that commit business changes. Such clicks require human
  confirmation; you may be told to wait.
- If a native confirm dialog will appear, call `expect_dialog` first.
- If you cannot make progress, are unsure whether an action is safe, or hit an error you cannot
  resolve with one obvious retry, call `escalate`. Do not guess in a bank system.
- Before `finish`, `declare_outcome` for non-success results this flow can show (e.g. "no record
  found", "access denied") based on what the UI reveals, and `extract` every output the goal asks for.
- Conditions must hold for any input: never use a balance, identifier, name or date you saw
  in this run as `success_text` or `detect_text`. Use headings, labels and column names.
- Stay within the allowed origin; policy will reject anything else.

Be terse in your text; put reasoning into the `why` fields."""

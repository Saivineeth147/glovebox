# Artifact Overfit Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it impossible for a discovery run to record a capability whose replay conditions are built from that run's own data.

**Architecture:** The model is corrected in-loop rather than after it. `Recorder` learns the values this run used and observed; the `declare_outcome` and `finish` tools consult it and raise, which surfaces to the model as a tool error it can retry — the same pattern the codebase already uses for expired element refs and unverifiable success text. A separate structural rule on `Capability` catches a terminal outcome that shadows the success path, needing no run data.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-09-12-studio-auth-ui-and-artifact-validation-design.md`

## Global Constraints

- No new runtime dependencies. Standard library only.
- Files stay under 400 lines; `schema/capability.py` is at 360 and `agent/recorder.py` at 293, so new logic goes in a new module rather than into either.
- Functions under 20 lines, max 3 parameters before an options object, max 3 nesting levels.
- Every new function gets a test; tests sit under `tests/unit/`.
- Test names read as sentences: `test_should_...`.
- Doc comments say **why**, not what.
- The committed `capabilities/member_savings_balance.json` (1.0.0) must keep validating — it is the regression baseline.

---

### Task 1: Overfit detection module

**Files:**
- Create: `src/glovebox/agent/overfit.py`
- Test: `tests/unit/test_overfit.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MIN_LITERAL_LENGTH: int`, `overfit_reason(text: str, literals: Sequence[str]) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from glovebox.agent.overfit import overfit_reason


def test_should_reject_text_containing_a_record_time_parameter_value() -> None:
    reason = overfit_reason("Member No. 100234", ["100234"])
    assert reason is not None and "100234" in reason


def test_should_reject_text_containing_a_multi_digit_literal() -> None:
    """The failed run's balance reached no parameter and no extraction, only the screen."""
    assert overfit_reason("$1250.75", []) is not None


def test_should_accept_a_static_label() -> None:
    assert overfit_reason("Regular Savings", ["100234"]) is None


def test_should_accept_a_single_digit_because_it_is_usually_part_of_a_label() -> None:
    assert overfit_reason("Page 1", []) is None


def test_should_ignore_short_literals_so_one_character_input_cannot_reject_everything() -> None:
    assert overfit_reason("Share Accounts", ["a"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'glovebox.agent.overfit'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Refuse replay conditions built from one run's data.

A discovery run sees one member, one balance, one date. A condition built from those
passes on the recorded input and fails on every other, while still satisfying the schema —
so the check has to live here rather than in validation alone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

MIN_LITERAL_LENGTH = 3
_MULTI_DIGIT = re.compile(r"\d{2,}")

_ADVICE = (
    "Replay conditions must hold for every input. Use static screen text such as a heading, "
    "label or column name instead."
)


def overfit_reason(text: str, literals: Sequence[str]) -> str | None:
    """Why `text` must not become a replay condition, or None when it is safe."""
    lowered = text.lower()
    for literal in literals:
        if len(literal) >= MIN_LITERAL_LENGTH and literal.lower() in lowered:
            return f"{text!r} contains {literal!r}, a value from this run. {_ADVICE}"
    if match := _MULTI_DIGIT.search(text):
        return f"{text!r} contains the number {match.group()!r}, which varies per input. {_ADVICE}"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/glovebox/agent/overfit.py tests/unit/test_overfit.py
git commit -m "Discovery: detect replay conditions built from one run's data"
```

---

### Task 2: Recorder remembers this run's literals

**Files:**
- Modify: `src/glovebox/agent/recorder.py` (`Recorder.__init__`, new `note_observed_value`, new `overfit_reason`)
- Test: `tests/unit/test_overfit.py` (append)

**Interfaces:**
- Consumes: `overfit_reason(text, literals)` from Task 1.
- Produces: `Recorder(..., param_values: dict[str, Any] | None = None)`, `Recorder.note_observed_value(value: str | None) -> None`, `Recorder.overfit_reason(text: str) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
from glovebox.agent.recorder import Recorder
from glovebox.schema.capability import Parameter, ParamType


def _recorder(**kw):
    return Recorder(
        capability_id="c",
        app_id="a",
        tenant=None,
        entry_url="http://127.0.0.1:8089/t/alpha/",
        params=[Parameter(name="member_id", type=ParamType.STRING, description="d")],
        model_name="test",
        run_id="r",
        **kw,
    )


def test_should_reject_a_condition_built_from_a_parameter_value_it_was_given() -> None:
    rec = _recorder(param_values={"member_id": "100234"})
    assert rec.overfit_reason("Member No. 100234") is not None


def test_should_reject_a_condition_built_from_a_value_read_off_the_screen() -> None:
    rec = _recorder()
    rec.note_observed_value("Doe, Jane")
    assert rec.overfit_reason("Name Doe, Jane") is not None


def test_should_accept_a_static_label_when_values_are_known() -> None:
    rec = _recorder(param_values={"member_id": "100234"})
    assert rec.overfit_reason("Share Accounts") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'param_values'`

- [ ] **Step 3: Write minimal implementation**

Add the import at the top of `recorder.py`:

```python
from glovebox.agent.overfit import MIN_LITERAL_LENGTH, overfit_reason
```

Add `param_values: dict[str, Any] | None = None` to the keyword-only signature of `Recorder.__init__` and, at the end of its body:

```python
        # Values this run used or saw. Conditions built from them cannot generalize.
        self._literals: list[str] = [
            str(v) for v in (param_values or {}).values() if len(str(v)) >= MIN_LITERAL_LENGTH
        ]
```

Add two methods after `_add`:

```python
    def note_observed_value(self, value: str | None) -> None:
        """Remember a value read off the screen so a condition cannot be built from it."""
        if value and len(value) >= MIN_LITERAL_LENGTH:
            self._literals.append(str(value))

    def overfit_reason(self, text: str) -> str | None:
        """Why `text` must not become a replay condition, or None when it is safe."""
        return overfit_reason(text, self._literals)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/glovebox/agent/recorder.py tests/unit/test_overfit.py
git commit -m "Recorder: remember the values this run used and saw"
```

---

### Task 3: The tools refuse overfit conditions

**Files:**
- Modify: `src/glovebox/agent/loop.py` (`__init__` recorder construction, `_t_extract`, `_t_declare_outcome`, `_t_finish`)
- Modify: `src/glovebox/agent/tools.py` (SYSTEM_PROMPT guidance)
- Test: `tests/unit/test_overfit.py` (append)

**Interfaces:**
- Consumes: `Recorder.overfit_reason`, `Recorder.note_observed_value` from Task 2.
- Produces: no new public names; `_t_declare_outcome` and `_t_finish` raise `ValueError` on overfit text, which `_dispatch` already converts into a tool error the model sees.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from glovebox.agent.loop import DiscoveryLoop


def test_should_refuse_to_declare_an_outcome_built_from_run_data() -> None:
    """The model gets a tool error and can retry, rather than the run dying at build time."""
    loop = object.__new__(DiscoveryLoop)
    loop.recorder = _recorder(param_values={"member_id": "100234"})
    with pytest.raises(ValueError, match="100234"):
        DiscoveryLoop._t_declare_outcome(loop, "MEMBER_FOUND", "found", "Member No. 100234")
    assert loop.recorder.outcomes == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: FAIL — `Failed: DID NOT RAISE <class 'ValueError'>`

- [ ] **Step 3: Write minimal implementation**

In `loop.py` `__init__`, add `param_values=params,` to the `Recorder(...)` call.

In `_t_extract`, after `value` is computed and before the `log.emit`, add:

```python
        self.recorder.note_observed_value(str(value) if value is not None else None)
```

At the top of `_t_declare_outcome`:

```python
        if reason := self.recorder.overfit_reason(detect_text):
            raise ValueError(f"detect_text rejected: {reason}")
```

In `_t_finish`, inside the existing `for t in success_text:` loop, before the visibility check:

```python
            if reason := self.recorder.overfit_reason(t):
                raise ValueError(f"success_text rejected: {reason}")
```

In `tools.py`, append to the SYSTEM_PROMPT "How to work" list:

```
- Conditions must hold for any input: never use a balance, identifier, name or date you saw in
  this run as `success_text` or `detect_text`. Use headings, labels and column names.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/glovebox/agent/loop.py src/glovebox/agent/tools.py tests/unit/test_overfit.py
git commit -m "Discovery: reject run-specific conditions as a retryable tool error"
```

---

### Task 4: A terminal outcome may not shadow the success path

**Files:**
- Modify: `src/glovebox/schema/capability.py` (`Capability._consistent`)
- Test: `tests/unit/test_overfit.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks — this is a structural rule needing no run data.
- Produces: a `ValueError` from `Capability` validation when a terminal outcome's detector overlaps a success condition.

- [ ] **Step 1: Write the failing test**

```python
import json
import subprocess

from glovebox.schema.capability import Capability


def _committed_artifact() -> dict:
    return json.loads(
        subprocess.run(
            ["git", "show", "HEAD:capabilities/member_savings_balance.json"],
            capture_output=True, text=True, check=True,
        ).stdout
    )


def test_should_reject_a_terminal_outcome_that_matches_the_success_screen() -> None:
    """MEMBER_FOUND ended the run before extraction and returned no outputs."""
    doc = _committed_artifact()
    doc["outcomes"] = [{
        "code": "MEMBER_FOUND",
        "description": "found",
        "detect": {"kind": "text_visible", "value": "Regular Savings balance", "timeout_ms": 0},
        "terminal": True,
    }]
    with pytest.raises(ValueError, match="MEMBER_FOUND"):
        Capability.model_validate(doc)


def test_should_keep_accepting_the_committed_artifact() -> None:
    assert Capability.model_validate(_committed_artifact()).id == "member_savings_balance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: FAIL on the first test — `DID NOT RAISE`. The second passes already.

- [ ] **Step 3: Write minimal implementation**

Append to `Capability._consistent`, before `return self`:

```python
        success_values = [c.value.lower() for c in self.success if c.value]
        for outcome in self.outcomes:
            detected = (outcome.detect.value or "").lower()
            if not (detected and outcome.terminal):
                continue
            if any(detected in s or s in detected for s in success_values):
                raise ValueError(
                    f"terminal outcome {outcome.code!r} is detected by text that also appears in "
                    "the success conditions; it would end the run on the success screen before "
                    "outputs are extracted"
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_overfit.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add src/glovebox/schema/capability.py tests/unit/test_overfit.py
git commit -m "Schema: a terminal outcome may not shadow the success screen"
```

---

### Task 5: Re-record and prove it generalizes

**Files:**
- Modify: `capabilities/member_savings_balance.json` (regenerated)
- Modify: `evidence/discovery/` (regenerated)

**Interfaces:**
- Consumes: everything above.
- Produces: a capability whose `provenance.model` is a real model and which replays for three different members.

- [ ] **Step 1: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all green.

- [ ] **Step 2: Start the target app**

Run: `uv run glovebox target serve --port 8089` in the background.
Expected: `http://127.0.0.1:8089/` returns HTTP 307.

- [ ] **Step 3: Re-record**

```bash
uv run glovebox discover \
  --goal "Look up member 100234 and read their current savings balance" \
  --app-url http://127.0.0.1:8089/ --capability-name member_savings_balance \
  --param member_id=100234 --evidence-dir evidence/discovery
```

Expected: `discovery success`, and `provenance.model` is `openrouter:anthropic/claude-sonnet-5`.

- [ ] **Step 4: Prove it generalizes**

For each of `100234`, `100235`, `100999`:

```bash
uv run glovebox replay capabilities/member_savings_balance.json \
  --param member_id=<id> --allow-draft --evidence-dir <scratchpad>/gen-<id>
```

Expected: `100234` and `100235` return `status: success` with non-empty `outputs`; `100999` returns the `MEMBER_NOT_FOUND` business outcome. If any condition still carries run data, the recorder change did not hold — stop and fix rather than approving.

- [ ] **Step 5: Approve, restore the evidence README, and commit**

```bash
uv run glovebox catalog approve member_savings_balance "$USER" --notes "reviewed steps, outcomes and risk"
git checkout evidence/discovery/README.md
uv run pytest -q
git add capabilities/ evidence/discovery/
git commit -m "Capability: re-record member_savings_balance from a real model run"
```

Expected: `test_committed_capability_is_valid_and_approved` passes again.

"""Propose a replacement locator when a recorded one stops resolving. Never apply one.

REPORT.md §7 lists assisted repair as the next thing to build, with the
condition that matters: the model may suggest, and a human disposes. A capability that healed
itself at replay time would put a model back in the production path and hand a reviewer an
artifact nobody approved, which is the whole thing this system is arranged to avoid.

So this is deliberately small. One call, no retries, and the suggestion is thrown away unless
it resolves to exactly one element on the screen that is actually there — the same uniqueness
rule every recorded strategy has to satisfy. What survives is written out as a proposal for
review; the run still fails.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from glovebox.schema.capability import Target, TargetStrategy
from glovebox.surface.base import Element
from glovebox.surface.web import locators

MAX_ELEMENTS_SHOWN = 60

SYSTEM_PROMPT = (
    "You repair a broken UI locator for a back-office automation. You are given the control a "
    "recorded step used to find, and the controls actually on screen now. Answer with one JSON "
    'object and nothing else: {"kind": ..., "value": {...}}, choosing the most stable kind '
    "available (role_name, label, name_attr, text, table_cell). If no control on screen is "
    "plausibly the same one, answer {}."
)


class OneShotLLM(Protocol):
    """The narrowest model interface a repair needs: one prompt, one answer."""

    def complete(self, system: str, prompt: str) -> str: ...


@dataclass(frozen=True)
class RepairProposal:
    """A locator the model suggested, which resolved uniquely, and which nobody has approved."""

    strategy: TargetStrategy
    replaces: str
    resolved_to: str

    def write(self, run_dir: Path, step_id: str) -> str:
        """Record the proposal beside the run's evidence, marked as not applied."""
        path = Path(run_dir) / "repair-proposal.json"
        path.write_text(
            json.dumps(
                {
                    "status": "proposed",
                    "step_id": step_id,
                    "replaces": self.replaces,
                    "resolved_to": self.resolved_to,
                    "strategy": self.strategy.model_dump(mode="json"),
                    "note": (
                        "Not applied. Re-record the capability, or add this as a tenant "
                        "override, and have it reviewed before it runs unattended."
                    ),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(path)


def _describe_screen(elements: list[Element]) -> str:
    return "\n".join(e.summary() for e in elements[:MAX_ELEMENTS_SHOWN])


def _parse(answer: str) -> TargetStrategy | None:
    try:
        payload: dict[str, Any] = json.loads(answer)
        return TargetStrategy(
            kind=payload["kind"], value=payload["value"], robustness="proposed by repair"
        )
    except Exception:
        # A malformed answer is simply no proposal; the caller's failure stands either way.
        return None


def propose_strategy(
    target: Target, elements: list[Element], llm: OneShotLLM
) -> RepairProposal | None:
    """Ask once for a replacement locator, and keep it only if it resolves to exactly one control."""
    prompt = (
        f"The recorded control was: {target.description}\n"
        f"Its strategies were: {json.dumps([s.value for s in target.strategies])}\n\n"
        f"Controls on screen now:\n{_describe_screen(elements)}"
    )
    strategy = _parse(llm.complete(SYSTEM_PROMPT, prompt))
    if strategy is None:
        return None
    candidate = Target(description=target.description, frame=target.frame, strategies=[strategy])
    try:
        resolved = locators.resolve(candidate, elements)
    except Exception:
        # Unresolvable or ambiguous: ambiguity is the failure this system exists to avoid, and
        # a proposal that reintroduces it is worse than none.
        return None
    return RepairProposal(
        strategy=strategy, replaces=target.description, resolved_to=resolved.element.summary()
    )

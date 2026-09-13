"""A proposal is not a repair: the model may suggest a locator, never apply one."""

from __future__ import annotations

import json
from pathlib import Path

from glovebox.repair import RepairProposal, propose_strategy
from glovebox.schema.capability import Target, TargetStrategy
from glovebox.surface.base import Element


def _element(ref: str, role: str, name: str) -> Element:
    return Element(
        ref=ref,
        frame=[],
        role=role,
        name=name,
        text=name,
        label=None,
        name_attr=None,
        tag="input",
        css=f"#{ref}",
        bbox=(0.0, 0.0, 10.0, 10.0),
        nbox=(0.1, 0.1),
        interactive=True,
        page_box=(0.0, 0.0, 10.0, 10.0),
    )


def _target() -> Target:
    return Target(
        description="button 'Find Member'",
        strategies=[
            TargetStrategy(
                kind="role_name", value={"role": "button", "name": "Find Member"}, robustness="r"
            )
        ],
    )


class _StubLLM:
    """Stands in for the model: one call, one answer, no network."""

    name = "stub"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def complete(self, system: str, prompt: str) -> str:
        self.calls += 1
        return self.answer


def test_should_propose_a_strategy_that_names_an_element_actually_on_screen() -> None:
    llm = _StubLLM(json.dumps({"kind": "role_name", "value": {"role": "button", "name": "Search"}}))
    proposal = propose_strategy(_target(), [_element("e1", "button", "Search")], llm)
    assert isinstance(proposal, RepairProposal)
    assert proposal.strategy.kind == "role_name"
    assert proposal.strategy.value["name"] == "Search"


def test_should_refuse_a_proposal_that_matches_nothing_on_screen() -> None:
    """An unresolvable suggestion is worse than none: it would waste the reviewer's time."""
    llm = _StubLLM(json.dumps({"kind": "role_name", "value": {"role": "button", "name": "Nope"}}))
    assert propose_strategy(_target(), [_element("e1", "button", "Search")], llm) is None


def test_should_refuse_a_proposal_that_matches_more_than_one_element() -> None:
    """Ambiguity is the failure this system exists to avoid; a repair must not reintroduce it."""
    llm = _StubLLM(json.dumps({"kind": "role_name", "value": {"role": "button", "name": "Go"}}))
    elements = [_element("e1", "button", "Go"), _element("e2", "button", "Go")]
    assert propose_strategy(_target(), elements, llm) is None


def test_should_survive_a_model_answer_that_is_not_json() -> None:
    assert (
        propose_strategy(_target(), [_element("e1", "button", "Search")], _StubLLM("sorry")) is None
    )


def test_should_ask_the_model_exactly_once() -> None:
    """Bounded by construction: a repair loop that retries is a model in the replay path."""
    llm = _StubLLM(json.dumps({"kind": "role_name", "value": {"role": "button", "name": "Search"}}))
    propose_strategy(_target(), [_element("e1", "button", "Search")], llm)
    assert llm.calls == 1


def test_a_proposal_should_record_what_it_replaces_and_stay_unapplied(tmp_path: Path) -> None:
    llm = _StubLLM(json.dumps({"kind": "role_name", "value": {"role": "button", "name": "Search"}}))
    target = _target()
    proposal = propose_strategy(target, [_element("e1", "button", "Search")], llm)
    assert proposal is not None
    written = proposal.write(tmp_path, step_id="s08_click")
    saved = json.loads(Path(written).read_text())
    assert saved["step_id"] == "s08_click"
    assert saved["status"] == "proposed"
    assert saved["replaces"] == target.description

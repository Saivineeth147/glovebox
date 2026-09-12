"""Compare two independent recordings of the same goal.

Six live discovery runs of one goal produced six materially different artifacts, and every
one of them validated. A single recording therefore says less than it appears to: parts of it
are properties of the application, and parts are an accident of one model sample. Running
discovery twice and comparing separates the two, and the parts both runs agree on are the
parts a reviewer can approve without re-reading every locator.

This reports disagreement rather than merging: a merged artifact would be one neither run
produced, and nothing would have exercised it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from glovebox.schema.capability import Capability


@dataclass(frozen=True)
class Divergence:
    """One aspect the two recordings did not agree on."""

    aspect: str
    detail: str


def _action_sequence(capability: Capability) -> list[str]:
    return [str(step.action) for step in capability.steps]


def _success_values(capability: Capability) -> set[str]:
    return {c.value for c in capability.success if c.value}


def _outcome_codes(capability: Capability) -> set[str]:
    return {outcome.code for outcome in capability.outcomes}


def _outputs(capability: Capability) -> set[tuple[str, str]]:
    return {(output.name, str(output.type)) for output in capability.outputs}


def _locator_kinds(capability: Capability) -> list[str]:
    """The strategy each targeted step leads with, in order.

    Comparing action kinds alone would call two runs identical when one reads the balance
    cell and the other reads the member number, since both are an `extract`. What a reviewer
    needs to know is whether the two runs addressed the same controls the same way.
    """
    return [
        f"{step.action}:{step.target.strategies[0].kind}"
        for step in capability.steps
        if step.target and step.target.strategies
    ]


def _describe_set_difference(first: set[Any], second: set[Any]) -> str:
    only_first = sorted(str(item) for item in first - second)
    only_second = sorted(str(item) for item in second - first)
    parts = []
    if only_first:
        parts.append(f"only in the first run: {', '.join(only_first)}")
    if only_second:
        parts.append(f"only in the second run: {', '.join(only_second)}")
    return "; ".join(parts)


def compare(first: Capability, second: Capability) -> list[Divergence]:
    """Every aspect the two recordings disagree on, in review order."""
    divergences: list[Divergence] = []
    first_actions, second_actions = _action_sequence(first), _action_sequence(second)
    if first_actions != second_actions:
        divergences.append(
            Divergence(
                "steps",
                f"{' → '.join(first_actions)} versus {' → '.join(second_actions)}",
            )
        )
    first_locators, second_locators = _locator_kinds(first), _locator_kinds(second)
    if first_locators != second_locators:
        divergences.append(
            Divergence(
                "locators",
                f"{', '.join(first_locators)} versus {', '.join(second_locators)}",
            )
        )
    for aspect, reader in (
        ("success", _success_values),
        ("outcomes", _outcome_codes),
        ("outputs", _outputs),
    ):
        detail = _describe_set_difference(reader(first), reader(second))
        if detail:
            divergences.append(Divergence(aspect, detail))
    return divergences


#: Aspects compared, so agreement is a fraction of a fixed denominator rather than of
#: however many disagreements happened to be found.
COMPARED_ASPECTS = ("steps", "locators", "success", "outcomes", "outputs")


def agreement(first: Capability, second: Capability) -> float:
    """Fraction of the compared aspects the two recordings agree on."""
    disagreed = {divergence.aspect for divergence in compare(first, second)}
    return (len(COMPARED_ASPECTS) - len(disagreed)) / len(COMPARED_ASPECTS)


def format_agreement(first: Capability, second: Capability, labels: tuple[str, str]) -> Any:
    """A table of what two recordings disagree on, headed by the fraction they share."""
    from rich.table import Table

    score = agreement(first, second)
    divergences = compare(first, second)
    table = Table(
        title=f"{labels[0]} vs {labels[1]} — agree on {score:.0%} of what was compared",
        box=None,
        pad_edge=False,
    )
    table.add_column("aspect")
    table.add_column("disagreement")
    if not divergences:
        table.add_row("—", "the two recordings agree on every aspect compared")
    for divergence in divergences:
        table.add_row(divergence.aspect, divergence.detail)
    return table

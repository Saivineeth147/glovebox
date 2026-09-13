"""How reliable the catalog actually is, as opposed to how much history it has accumulated.

The first version of this counted every replay the runs directory had ever seen. That made the
headline number a record of development — artifact versions that no longer exist, runs the
approval gate deliberately refused — and it scored a correct MEMBER_NOT_FOUND as a failure. It
read 78% on a catalog whose current artifacts replay 20 times out of 20.

So the question is narrowed to the one worth asking: when an agent invokes an approved
capability normally, does it get a usable answer? What is set aside is counted and reported
rather than quietly dropped, because a rate with invisible exclusions is how the first one
went wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Both are answers the result contract promises. A business outcome is the flow reporting
#: something the caller branches on, not the capability failing to run.
ANSWERED = {"success", "business_outcome"}

#: Refused before the capability did anything: a draft artifact, or parameters the caller did
#: not supply. Neither says whether the capability works.
REFUSED_BEFORE_RUNNING = {"not_approved", "input_invalid"}


@dataclass(frozen=True)
class ReplayHealth:
    """Answered over eligible, with everything set aside accounted for."""

    answered: int
    eligible: int
    superseded: int
    refused: int

    @property
    def rate(self) -> float | None:
        return self.answered / self.eligible if self.eligible else None


def _failure_class(run: dict[str, Any]) -> str | None:
    failure = (run.get("result") or {}).get("failure") or {}
    return failure.get("failure_class")


def replay_health(runs: list[dict[str, Any]], current_versions: dict[str, str]) -> ReplayHealth:
    """Measure the catalog's current artifacts against the replays that exercised them."""
    answered = eligible = superseded = refused = 0
    for run in runs:
        if run.get("kind") != "replay" or run.get("status") == "running":
            continue
        capability = str(run.get("capability_id") or "")
        if current_versions.get(capability) != run.get("capability_version"):
            superseded += 1
            continue
        if _failure_class(run) in REFUSED_BEFORE_RUNNING:
            refused += 1
            continue
        eligible += 1
        answered += run.get("status") in ANSWERED
    return ReplayHealth(
        answered=answered, eligible=eligible, superseded=superseded, refused=refused
    )

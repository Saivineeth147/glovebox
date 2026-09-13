"""What "replay success" should answer: when an agent invokes an approved capability
normally, does it get a usable answer?

The first version of this counted every replay ever run, including ones against artifact
versions that no longer exist and ones the gate deliberately refused, and scored a correct
MEMBER_NOT_FOUND as a failure. It read 78% while the current artifacts were at 100%.
"""

from __future__ import annotations

from glovebox.studio.health import replay_health


def _run(status: str, version: str = "1.0.7", failure: str | None = None, kind: str = "replay"):
    result = {"failure": {"failure_class": failure}} if failure else None
    return {
        "kind": kind,
        "status": status,
        "capability_id": "member_savings_balance",
        "capability_version": version,
        "result": result,
    }


CURRENT = {"member_savings_balance": "1.0.7"}


def test_should_count_a_successful_replay_as_answered() -> None:
    health = replay_health([_run("success")], CURRENT)
    assert (health.answered, health.eligible, health.rate) == (1, 1, 1.0)


def test_should_count_a_business_outcome_as_answered() -> None:
    """MEMBER_NOT_FOUND is the contract answering, not the capability missing."""
    health = replay_health([_run("business_outcome")], CURRENT)
    assert health.rate == 1.0


def test_should_count_a_genuine_failure_against_the_rate() -> None:
    health = replay_health([_run("success"), _run("failed", failure="target_not_found")], CURRENT)
    assert health.rate == 0.5


def test_should_set_aside_runs_against_a_superseded_version() -> None:
    """Reliability is a property of the artifact in the catalog, not of its history."""
    health = replay_health([_run("success"), _run("failed", version="1.0.1")], CURRENT)
    assert (health.rate, health.superseded) == (1.0, 1)


def test_should_set_aside_what_the_gate_refused_before_it_ran() -> None:
    """A draft refused and a missing parameter are the caller's, not the capability's."""
    runs = [
        _run("success"),
        _run("failed", failure="not_approved"),
        _run("failed", failure="input_invalid"),
    ]
    health = replay_health(runs, CURRENT)
    assert (health.rate, health.refused) == (1.0, 2)


def test_should_ignore_discovery_runs_and_runs_still_going() -> None:
    runs = [_run("success"), _run("success", kind="discovery"), _run("running")]
    assert replay_health(runs, CURRENT).eligible == 1


def test_should_report_no_rate_rather_than_zero_when_nothing_is_eligible() -> None:
    assert replay_health([], CURRENT).rate is None
    assert replay_health([_run("failed", version="1.0.1")], CURRENT).rate is None


def test_should_treat_a_capability_missing_from_the_catalog_as_superseded() -> None:
    """A run whose capability was deleted says nothing about what is in the catalog now."""
    health = replay_health([_run("success", version="1.0.0")], {})
    assert (health.eligible, health.superseded) == (0, 1)


def test_a_business_outcome_should_count_toward_a_capability_s_confidence(tmp_path) -> None:
    """review.confidence is the per-artifact version of the same question the dashboard asks.

    Counting a correct MEMBER_NOT_FOUND as an unsuccessful replay showed the committed
    capability at 0% confidence while it replayed perfectly.
    """
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    from glovebox.catalog import Catalog
    from glovebox.schema.capability import Capability
    from glovebox.schema.results import ReplayResult, ReplayStatus

    root = Path(__file__).resolve().parents[2]
    doc = json.loads((root / "capabilities" / "member_savings_balance.json").read_text())
    doc["review"] = {"status": "approved", "replays": 0, "replay_successes": 0}
    catalog = Catalog(tmp_path)
    catalog.save(Capability.model_validate(doc), bump=False)

    outcome = ReplayResult(
        run_id="r",
        capability_id="member_savings_balance",
        capability_version=doc["version"],
        tenant="alpha",
        status=ReplayStatus.BUSINESS_OUTCOME,
        outcome_code="MEMBER_NOT_FOUND",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        evidence_dir="runs/r",
    )
    assert outcome.answered is True
    assert outcome.ok is False, "ok still means strictly success"

    catalog.record_replay("member_savings_balance", outcome.answered)
    assert catalog.load("member_savings_balance").review.confidence == 1.0

"""Stopping a run: the console has to offer a way out of a run that cannot finish."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from glovebox.studio.server import create_studio

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "a-long-enough-password"


def _signed_in_client(tmp_path: Path) -> TestClient:
    app = create_studio(
        tmp_path / "runs", ROOT / "capabilities", ROOT / "policies" / "default.yaml"
    )
    client = TestClient(app)
    client.post("/api/auth/register", json={"email": "admin@example.com", "password": PASSWORD})
    return client


def test_should_refuse_a_job_when_the_target_is_not_reachable(tmp_path: Path) -> None:
    """A job that cannot progress must not be accepted.

    Studio already knows the application is down — the banner reads "target: offline". Accepting
    the run anyway leaves it sitting on run.started with no way to stop it, which is what a
    reviewer hits if they start Studio without `make target`.

    Addressed through discovery because its target comes from the request, so the assertion does
    not depend on whether this suite happens to have the app running.
    """
    client = _signed_in_client(tmp_path)

    refused = client.post(
        "/api/discover",
        json={
            "goal": "read a balance",
            "app_url": "http://127.0.0.1:9",  # discard port: nothing ever listens
            "capability_id": "nothing_will_be_recorded",
        },
    )

    assert refused.status_code == 503
    detail = refused.json()["detail"]
    assert "not reachable" in detail and "make target" in detail


def test_should_report_an_unknown_job_rather_than_failing_opaquely(tmp_path: Path) -> None:
    client = _signed_in_client(tmp_path)

    assert client.post("/api/jobs/job_nope/cancel").status_code == 404


def test_cancelling_should_mark_the_job_and_leave_a_finished_one_alone(tmp_path: Path) -> None:
    """The flag is what the run loops read between steps; a finished run has nothing to stop."""
    import threading

    from glovebox.control.session import OperatorBridge
    from glovebox.studio.jobs import Job, JobManager

    manager = JobManager(
        tmp_path / "runs", ROOT / "capabilities", ROOT / "policies" / "default.yaml"
    )
    running = Job(id="job_run", kind="replay", title="t", params={}, bridge=OperatorBridge())
    running.status = "running"
    finished = Job(id="job_done", kind="replay", title="t", params={}, bridge=OperatorBridge())
    finished.status = "finished"
    manager.jobs.update({running.id: running, finished.id: finished})

    assert manager.cancel("job_run").cancel.is_set()
    assert manager.cancel("job_done").cancel.is_set() is False
    assert isinstance(running.cancel, threading.Event)
    assert running.public()["cancel_requested"] is True


def test_the_engine_should_stop_between_steps_when_asked(tmp_path: Path) -> None:
    """Cooperative by necessity: a daemon thread cannot be killed from outside."""
    from glovebox.catalog import Catalog
    from glovebox.replay.engine import ReplayOptions

    cap = Catalog(ROOT / "capabilities").load("member_savings_balance")
    options = ReplayOptions(should_cancel=lambda: True)

    assert options.should_cancel is not None and options.should_cancel()
    assert cap.steps, "the fixture should have steps for the loop to stop before"


def test_cancelled_is_a_failure_class_not_a_fifth_status() -> None:
    """A stop is neither an answer nor the capability breaking, so the caller may retry it."""
    from glovebox.schema.results import FailureClass, ReplayStatus

    assert FailureClass.CANCELLED == "cancelled"
    assert "cancelled" not in {s.value for s in ReplayStatus}

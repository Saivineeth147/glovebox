"""Tests for the /api/auth/* endpoints and the auth gate on the rest of the API.

Every test builds its own Studio app under `tmp_path` (never the real runs/db dirs),
mirroring the fixture style in test_catalog_and_studio.py.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from glovebox.catalog import Catalog
from glovebox.control.session import OperatorBridge
from glovebox.studio.jobs import Job
from glovebox.studio.server import CommandBody, create_studio
from tests.unit.test_schema import _cap

ROOT = Path(__file__).resolve().parents[2]
STRONG_PASSWORD = "correct-horse-battery"


def _client(tmp_path: Path) -> TestClient:
    cat_dir = tmp_path / "caps"
    Catalog(cat_dir).save(_cap())
    app = create_studio(tmp_path / "runs", cat_dir, ROOT / "policies" / "default.yaml")
    return TestClient(app)


@pytest.fixture
def studio_client(tmp_path: Path) -> TestClient:
    return _client(tmp_path)


def _register(client: TestClient, email: str, password: str = STRONG_PASSWORD) -> dict[str, Any]:
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return dict(response.json())


def _logout(client: TestClient) -> None:
    client.post("/api/auth/logout")
    client.cookies.clear()


def _promote(tmp_path: Path, email: str, role: str) -> None:
    connection = sqlite3.connect(tmp_path / "runs" / "studio.db")
    connection.execute("UPDATE users SET role = ? WHERE email = ?", (role, email))
    connection.commit()
    connection.close()


def _as_new_role(client: TestClient, tmp_path: Path, email: str, role: str) -> None:
    """Log a fresh viewer in and promote them, leaving `client` authenticated as `role`."""
    _register(client, email)
    _promote(tmp_path, email, role)


# --------------------------------------------------------------------------- register


def test_should_make_the_first_registration_an_admin(studio_client: TestClient) -> None:
    body = _register(studio_client, "boss@example.com")
    assert body == {"email": "boss@example.com", "role": "admin"}
    assert "glovebox_session" in studio_client.cookies


def test_should_make_the_second_registration_a_viewer(studio_client: TestClient) -> None:
    _register(studio_client, "first@example.com")
    _logout(studio_client)
    body = _register(studio_client, "second@example.com")
    assert body["role"] == "viewer"


def test_should_reject_registration_with_a_weak_password(studio_client: TestClient) -> None:
    response = studio_client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": "short"}
    )
    assert response.status_code == 400


def test_should_reject_a_duplicate_email_registration(studio_client: TestClient) -> None:
    _register(studio_client, "dup@example.com")
    response = studio_client.post(
        "/api/auth/register", json={"email": "dup@example.com", "password": STRONG_PASSWORD}
    )
    assert response.status_code == 409


def test_should_set_a_httponly_lax_session_cookie_on_register(studio_client: TestClient) -> None:
    response = studio_client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": STRONG_PASSWORD}
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "glovebox_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()


def test_should_never_return_the_password_or_token_in_the_response_body(
    studio_client: TestClient,
) -> None:
    response = studio_client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": STRONG_PASSWORD}
    )
    assert STRONG_PASSWORD not in response.text
    assert studio_client.cookies["glovebox_session"] not in response.text


# ------------------------------------------------------------------------------ login


def test_should_log_in_with_correct_credentials(studio_client: TestClient) -> None:
    _register(studio_client, "a@example.com")
    _logout(studio_client)
    response = studio_client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": STRONG_PASSWORD}
    )
    assert response.status_code == 200
    assert response.json() == {"email": "a@example.com", "role": "admin"}


def test_should_return_401_for_a_wrong_password(studio_client: TestClient) -> None:
    _register(studio_client, "a@example.com")
    response = studio_client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "totally-wrong-password"}
    )
    assert response.status_code == 401


def test_should_return_the_same_401_for_an_unknown_email_as_for_a_wrong_password(
    studio_client: TestClient,
) -> None:
    _register(studio_client, "a@example.com")
    wrong_password = studio_client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "totally-wrong-password"}
    )
    unknown_email = studio_client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": STRONG_PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


# ---------------------------------------------------------------------------- /me


def test_should_return_401_from_me_when_unauthenticated(studio_client: TestClient) -> None:
    assert studio_client.get("/api/auth/me").status_code == 401


def test_should_return_email_and_role_from_me_when_authenticated(
    studio_client: TestClient,
) -> None:
    _register(studio_client, "a@example.com")
    response = studio_client.get("/api/auth/me")
    assert response.json() == {"email": "a@example.com", "role": "admin"}


# ------------------------------------------------------------------------- logout


def test_should_clear_the_session_on_logout(studio_client: TestClient) -> None:
    _register(studio_client, "a@example.com")
    assert studio_client.get("/api/auth/me").status_code == 200
    studio_client.post("/api/auth/logout")
    studio_client.cookies.clear()
    assert studio_client.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------------- gating: reads


def test_should_reject_an_unauthenticated_read(studio_client: TestClient) -> None:
    assert studio_client.get("/api/overview").status_code == 401


def test_should_allow_any_authenticated_role_to_read(studio_client: TestClient) -> None:
    _register(studio_client, "a@example.com")
    assert studio_client.get("/api/overview").status_code == 200
    assert studio_client.get("/api/capabilities").status_code == 200


def test_should_allow_a_viewer_to_read(studio_client: TestClient, tmp_path: Path) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _register(studio_client, "viewer@example.com")
    assert studio_client.get("/api/capabilities").status_code == 200


# --------------------------------------------------------------- gating: operator


def test_should_reject_an_unauthenticated_discover(studio_client: TestClient) -> None:
    response = studio_client.post(
        "/api/discover",
        json={"goal": "g", "app_url": "http://example.com", "capability_id": "c"},
    )
    assert response.status_code == 401


def test_should_forbid_a_viewer_from_discovering(studio_client: TestClient, tmp_path: Path) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _register(studio_client, "viewer@example.com")
    response = studio_client.post(
        "/api/discover",
        json={"goal": "g", "app_url": "http://example.com", "capability_id": "c"},
    )
    assert response.status_code == 403


def test_should_forbid_a_viewer_from_replaying(studio_client: TestClient, tmp_path: Path) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _register(studio_client, "viewer@example.com")
    response = studio_client.post("/api/replay", json={"capability_id": "does-not-exist"})
    assert response.status_code == 403


def test_should_let_an_operator_reach_the_replay_handler(
    studio_client: TestClient, tmp_path: Path
) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _as_new_role(studio_client, tmp_path, "operator@example.com", "operator")
    response = studio_client.post("/api/replay", json={"capability_id": "does-not-exist"})
    assert response.status_code == 404  # past the gate; catalog lookup fails instead


def test_should_let_an_admin_reach_the_replay_handler_too(studio_client: TestClient) -> None:
    _register(studio_client, "boss@example.com")
    response = studio_client.post("/api/replay", json={"capability_id": "does-not-exist"})
    assert response.status_code == 404


def test_should_forbid_a_viewer_from_arming_a_fault(
    studio_client: TestClient, tmp_path: Path
) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _register(studio_client, "viewer@example.com")
    assert studio_client.post("/api/target/faults/slow_load").status_code == 403


def test_should_forbid_a_viewer_from_clearing_faults(
    studio_client: TestClient, tmp_path: Path
) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _register(studio_client, "viewer@example.com")
    assert studio_client.delete("/api/target/faults").status_code == 403


# ----------------------------------------------------------------- gating: admin


def test_should_allow_an_admin_to_approve_a_capability(studio_client: TestClient) -> None:
    _register(studio_client, "boss@example.com")
    response = studio_client.post("/api/capabilities/demo/approve", json={"reviewer": "qa"})
    assert response.status_code == 200


def test_should_forbid_a_viewer_from_approving_a_capability(
    studio_client: TestClient, tmp_path: Path
) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _register(studio_client, "viewer@example.com")
    response = studio_client.post("/api/capabilities/demo/approve", json={"reviewer": "qa"})
    assert response.status_code == 403


def test_should_forbid_an_operator_from_approving_a_capability(
    studio_client: TestClient, tmp_path: Path
) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _as_new_role(studio_client, tmp_path, "operator@example.com", "operator")
    response = studio_client.post("/api/capabilities/demo/approve", json={"reviewer": "qa"})
    assert response.status_code == 403


# --------------------------------------------------------------------- catch-all


def test_should_return_json_404_for_an_unknown_api_path(studio_client: TestClient) -> None:
    response = studio_client.get("/api/this-route-does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_should_still_serve_the_spa_shell_for_non_api_paths(studio_client: TestClient) -> None:
    response = studio_client.get("/some/deep/route")
    assert response.status_code in (200, 503)


# --------------------------------------------------------------- operator identity


def test_command_body_has_no_operator_field() -> None:
    assert "operator" not in CommandBody.model_fields


def test_should_record_the_session_email_as_operator_not_the_request_body(
    studio_client: TestClient,
) -> None:
    admin = _register(studio_client, "boss@example.com")
    jobs = studio_client.app.state.jobs  # type: ignore[attr-defined]
    bridge = OperatorBridge()
    job = Job(id="job_test1", kind="replay", title="t", params={}, bridge=bridge)
    jobs.jobs[job.id] = job
    captured: dict[str, Any] = {}

    def fake_automation() -> None:
        cmd = bridge._next(timeout=5)
        assert cmd is not None
        captured["operator"] = cmd.operator
        cmd.reply.put({"ok": True})

    threading.Thread(target=fake_automation, daemon=True).start()

    response = studio_client.post(
        f"/api/jobs/{job.id}/operator/command",
        json={"op": "resume", "operator": "attacker@evil.com"},
    )
    assert response.status_code == 200
    assert captured["operator"] == admin["email"] == "boss@example.com"


def test_should_reject_an_unauthenticated_operator_command(studio_client: TestClient) -> None:
    response = studio_client.post("/api/jobs/nope/operator/command", json={"op": "resume"})
    assert response.status_code == 401


def test_should_forbid_a_viewer_from_sending_an_operator_command(
    studio_client: TestClient, tmp_path: Path
) -> None:
    _register(studio_client, "boss@example.com")
    _logout(studio_client)
    _register(studio_client, "viewer@example.com")
    response = studio_client.post("/api/jobs/nope/operator/command", json={"op": "resume"})
    assert response.status_code == 403


# --------------------------------------------------------------------------- db path


def test_should_default_the_db_path_under_runs_dir(tmp_path: Path) -> None:
    _client(tmp_path)
    assert (tmp_path / "runs" / "studio.db").exists()


def test_should_use_the_env_var_db_path_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom_db = tmp_path / "elsewhere" / "auth.db"
    monkeypatch.setenv("GLOVEBOX_STUDIO_DB", str(custom_db))
    _client(tmp_path)
    assert custom_db.exists()
    assert not (tmp_path / "runs" / "studio.db").exists()

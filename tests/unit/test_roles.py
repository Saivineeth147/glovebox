"""The role ladder has to be climbable, or Studio ships three rungs and one reachable step."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from glovebox.studio.server import create_studio

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "a-long-enough-password"


def _studio(tmp_path: Path) -> TestClient:
    app = create_studio(tmp_path / "runs", tmp_path / "caps", ROOT / "policies" / "default.yaml")
    return TestClient(app)


def _register(client: TestClient, email: str) -> dict:
    return client.post("/api/auth/register", json={"email": email, "password": PASSWORD}).json()


def test_should_let_an_admin_raise_a_viewer_to_operator(tmp_path: Path) -> None:
    client = _studio(tmp_path)
    _register(client, "admin@example.com")
    client.post("/api/auth/logout")
    viewer = _register(client, "viewer@example.com")
    assert viewer["role"] == "viewer"

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    promoted = client.post("/api/users/viewer@example.com/role", json={"role": "operator"})

    assert promoted.status_code == 200 and promoted.json()["role"] == "operator"


def test_should_refuse_a_viewer_trying_to_promote_themselves(tmp_path: Path) -> None:
    client = _studio(tmp_path)
    _register(client, "admin@example.com")
    client.post("/api/auth/logout")
    _register(client, "viewer@example.com")

    refused = client.post("/api/users/viewer@example.com/role", json={"role": "admin"})

    assert refused.status_code == 403


def test_should_list_accounts_for_an_admin_without_exposing_password_material(
    tmp_path: Path,
) -> None:
    client = _studio(tmp_path)
    _register(client, "admin@example.com")

    listed = client.get("/api/users")

    assert listed.status_code == 200
    assert [u["email"] for u in listed.json()] == ["admin@example.com"]
    assert "password_hash" not in listed.text and "salt" not in listed.text


def test_should_refuse_an_unknown_role_rather_than_storing_it(tmp_path: Path) -> None:
    client = _studio(tmp_path)
    _register(client, "admin@example.com")

    refused = client.post("/api/users/admin@example.com/role", json={"role": "superuser"})

    assert refused.status_code in (400, 422)

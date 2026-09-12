"""Tests for the sessions table: token creation, lookup, expiry and revocation.

Every test opens its own SQLite file under `tmp_path` -- never the real Studio database.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from glovebox.studio.sessions import SESSION_COOKIE_NAME, SESSION_LIFETIME_HOURS, SessionStore


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "studio.db")


def test_should_resolve_a_freshly_created_session_to_its_user(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(user_id=7)
    assert store.resolve(session.token) == 7


def test_should_not_resolve_an_unknown_token(tmp_path: Path) -> None:
    assert _store(tmp_path).resolve("not-a-real-token") is None


def test_should_not_resolve_a_deleted_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(user_id=1)
    store.delete(session.token)
    assert store.resolve(session.token) is None


def test_should_not_resolve_an_expired_session(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    store = SessionStore(db_path)
    session = store.create(user_id=1)
    expired_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    token_hash = hashlib.sha256(session.token.encode("utf-8")).hexdigest()
    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE sessions SET expires_at = ? WHERE token_sha256 = ?", (expired_at, token_hash)
    )
    connection.commit()
    connection.close()
    assert store.resolve(session.token) is None


def test_should_set_expiry_lifetime_hours_from_creation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before = datetime.now(UTC)
    session = store.create(user_id=1)
    expected = before + timedelta(hours=SESSION_LIFETIME_HOURS)
    assert abs((session.expires_at - expected).total_seconds()) < 5


def test_should_never_store_the_raw_token_value(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    store = SessionStore(db_path)
    session = store.create(user_id=1)
    raw = db_path.read_bytes()
    assert session.token.encode("utf-8") not in raw


def test_should_store_only_the_sha256_hash_of_the_token(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    store = SessionStore(db_path)
    session = store.create(user_id=1)
    expected_hash = hashlib.sha256(session.token.encode("utf-8")).hexdigest()
    connection = sqlite3.connect(db_path)
    row = connection.execute("SELECT token_sha256 FROM sessions WHERE user_id = ?", (1,)).fetchone()
    connection.close()
    assert row[0] == expected_hash


def test_should_use_the_documented_cookie_name() -> None:
    assert SESSION_COOKIE_NAME == "glovebox_session"


def test_should_generate_a_distinct_token_for_each_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create(user_id=1)
    second = store.create(user_id=1)
    assert first.token != second.token

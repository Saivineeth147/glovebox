"""Studio session tokens: a SQLite `sessions` table holding only token hashes.

Why hash-only storage: read access to the database file (a backup, a misconfigured
admin query, this same file inspected by a test) must never be enough to mint a valid
session -- only the original bearer token, which is never written to disk, can.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

SESSION_TOKEN_BYTES = 32
SESSION_LIFETIME_HOURS = 12
SESSION_COOKIE_NAME = "glovebox_session"
SQLITE_BUSY_TIMEOUT_SECONDS = 5.0

_CREATE_SESSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    token_sha256 TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class SessionToken:
    """The raw bearer token to hand to a client, alongside the row recording it."""

    token: str
    user_id: int
    expires_at: datetime


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore:
    """Owns the `sessions` table for one Studio database file."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        connection = self._connect()
        try:
            connection.execute(_CREATE_SESSIONS_TABLE_SQL)
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)

    def create(self, user_id: int) -> SessionToken:
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=SESSION_LIFETIME_HOURS)
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO sessions (token_sha256, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (_hash_token(token), user_id, created_at.isoformat(), expires_at.isoformat()),
            )
            connection.commit()
        finally:
            connection.close()
        return SessionToken(token=token, user_id=user_id, expires_at=expires_at)

    def resolve(self, token: str) -> int | None:
        """Return the session's user_id if `token` names a live, unexpired session."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_sha256 = ?",
                (_hash_token(token),),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        user_id, expires_at = row
        if datetime.fromisoformat(expires_at) < datetime.now(UTC):
            return None
        return int(user_id)

    def delete(self, token: str) -> None:
        connection = self._connect()
        try:
            connection.execute("DELETE FROM sessions WHERE token_sha256 = ?", (_hash_token(token),))
            connection.commit()
        finally:
            connection.close()

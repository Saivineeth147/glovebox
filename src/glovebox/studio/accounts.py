"""Studio user accounts: a SQLite `users` table plus password hashing.

No dependency is added for this -- stdlib `hashlib.scrypt` with a per-user salt and
`hmac.compare_digest` is exactly what a password-hashing library would call
underneath, and Studio has no other reason to carry one.

The first account ever registered becomes `admin`; every later one becomes `viewer`.
That assignment is done inside a single SQLite statement (see `_ROLE_FOR_NEW_USER_SQL`)
rather than a Python "count rows, then insert" check, because SQLite takes its write
lock at the start of a write statement -- before the statement's own subquery runs --
so two connections racing to register first can never both see an empty table.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

SCRYPT_SALT_LENGTH_BYTES = 16
SCRYPT_COST_FACTOR = 2**14
SCRYPT_BLOCK_SIZE = 8
SCRYPT_PARALLELIZATION = 1
SCRYPT_KEY_LENGTH_BYTES = 32
MINIMUM_PASSWORD_LENGTH = 12
SQLITE_BUSY_TIMEOUT_SECONDS = 5.0

# Only ever hashed against, never compared or stored: burns the same scrypt cost as a
# real lookup so a login attempt for an unregistered email takes about as long as one
# for a wrong password, and response latency doesn't reveal which emails are registered.
_DUMMY_SALT_FOR_UNKNOWN_EMAIL = b"0" * SCRYPT_SALT_LENGTH_BYTES


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AccountError(Exception):
    """Base class for account failures the API layer maps to a 4xx response."""


class WeakPasswordError(AccountError):
    """Raised when a password is shorter than MINIMUM_PASSWORD_LENGTH."""


class InvalidEmailError(AccountError):
    """Raised when an email has no '@' once trimmed."""


class EmailAlreadyRegisteredError(AccountError):
    """Raised when registration targets an email already in the users table."""


@dataclass(frozen=True)
class Account:
    """A registered user. Never carries the password hash past this module."""

    id: int
    email: str
    role: Role
    is_disabled: bool


_CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash BLOB NOT NULL,
    salt BLOB NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_disabled INTEGER NOT NULL DEFAULT 0
)
"""

# The subquery re-reads `users` from inside the same write statement that inserts into
# it, so its result is fixed by the write lock this statement already holds. Written as
# one literal (not composed with an f-string) so it reads as fixed SQL, not user input.
_INSERT_USER_SQL = """
INSERT INTO users (email, password_hash, salt, role, created_at, is_disabled)
VALUES (?, ?, ?, (SELECT CASE WHEN COUNT(*) = 0 THEN ? ELSE ? END FROM users), ?, 0)
"""


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise InvalidEmailError(f"not a valid email address: {email!r}")
    return normalized


def _require_strong_password(password: str) -> None:
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise WeakPasswordError(f"password must be at least {MINIMUM_PASSWORD_LENGTH} characters")


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_COST_FACTOR,
        r=SCRYPT_BLOCK_SIZE,
        p=SCRYPT_PARALLELIZATION,
        dklen=SCRYPT_KEY_LENGTH_BYTES,
    )


def _row_to_account(row: tuple[int, str, str, int]) -> Account:
    user_id, email, role, is_disabled = row
    return Account(id=user_id, email=email, role=Role(role), is_disabled=bool(is_disabled))


class AccountStore:
    """Owns the `users` table for one Studio database file."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        connection = self._connect()
        try:
            connection.execute(_CREATE_USERS_TABLE_SQL)
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
        connection.isolation_level = None  # explicit BEGIN/COMMIT below, not implicit ones
        return connection

    def register(self, email: str, password: str) -> Account:
        normalized_email = _normalize_email(email)
        _require_strong_password(password)
        salt = secrets.token_bytes(SCRYPT_SALT_LENGTH_BYTES)
        password_hash = _hash_password(password, salt)
        created_at = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            return self._insert_user(connection, normalized_email, password_hash, salt, created_at)
        finally:
            connection.close()

    def _insert_user(
        self,
        connection: sqlite3.Connection,
        email: str,
        password_hash: bytes,
        salt: bytes,
        created_at: str,
    ) -> Account:
        connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = connection.execute(
                _INSERT_USER_SQL,
                (email, password_hash, salt, Role.ADMIN.value, Role.VIEWER.value, created_at),
            )
            user_id = cursor.lastrowid
            assert user_id is not None  # set by sqlite3 on a successful INSERT
            new_role_row = connection.execute(
                "SELECT role FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            role = new_role_row[0]
        except sqlite3.IntegrityError as exc:
            connection.execute("ROLLBACK")
            raise EmailAlreadyRegisteredError(email) from exc
        connection.execute("COMMIT")
        return Account(id=user_id, email=email, role=Role(role), is_disabled=False)

    def authenticate(self, email: str, password: str) -> Account | None:
        """Return the account if `email`+`password` match a non-disabled user, else None.

        Deliberately returns the same "no match" result for an unknown email and for a
        wrong password -- the login route must not let a caller tell those apart.
        """
        try:
            normalized_email = _normalize_email(email)
        except InvalidEmailError:
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT id, password_hash, salt, role, is_disabled FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
        finally:
            connection.close()
        return self._check_password(row, normalized_email, password)

    def _check_password(
        self, row: tuple[int, bytes, bytes, str, int] | None, email: str, password: str
    ) -> Account | None:
        if row is None:
            _hash_password(password, _DUMMY_SALT_FOR_UNKNOWN_EMAIL)
            return None
        user_id, password_hash, salt, role, is_disabled = row
        if is_disabled or not hmac.compare_digest(_hash_password(password, salt), password_hash):
            return None
        return Account(id=user_id, email=email, role=Role(role), is_disabled=False)

    def get_by_id(self, user_id: int) -> Account | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT id, email, role, is_disabled FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _row_to_account(row)

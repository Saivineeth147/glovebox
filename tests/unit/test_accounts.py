"""Tests for the users table: registration, first-admin bootstrap, and password checks.

Every test opens its own SQLite file under `tmp_path` -- never the real Studio database.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from glovebox.studio.accounts import (
    Account,
    AccountError,
    AccountStore,
    EmailAlreadyRegisteredError,
    Role,
    WeakPasswordError,
)

STRONG_PASSWORD = "correct-horse-battery"  # 21 chars, well over the 12-char minimum


def _store(tmp_path: Path) -> AccountStore:
    return AccountStore(tmp_path / "studio.db")


def test_should_make_the_first_registered_account_an_admin(tmp_path: Path) -> None:
    account = _store(tmp_path).register("first@example.com", STRONG_PASSWORD)
    assert account.role == Role.ADMIN


def test_should_make_the_second_registered_account_a_viewer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register("first@example.com", STRONG_PASSWORD)
    second = store.register("second@example.com", STRONG_PASSWORD)
    assert second.role == Role.VIEWER


def test_should_assign_admin_race_safely_under_concurrent_registration(tmp_path: Path) -> None:
    """Ten threads register at once against one db file; exactly one may become admin.

    A Python-level check-then-insert would let every thread observe an empty table
    and all become admin -- the task requires this to happen inside one SQLite
    transaction instead, which this exercises directly.
    """
    store = _store(tmp_path)
    accounts: list[Account] = []
    lock = threading.Lock()

    def register(n: int) -> None:
        account = store.register(f"user{n}@example.com", STRONG_PASSWORD)
        with lock:
            accounts.append(account)

    threads = [threading.Thread(target=register, args=(n,)) for n in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    admins = [a for a in accounts if a.role == Role.ADMIN]
    assert len(accounts) == 10
    assert len(admins) == 1


def test_should_accept_a_password_of_exactly_twelve_characters(tmp_path: Path) -> None:
    account = _store(tmp_path).register("user@example.com", "123456789012")
    assert account.role == Role.ADMIN


def test_should_reject_a_password_shorter_than_twelve_characters(tmp_path: Path) -> None:
    with pytest.raises(WeakPasswordError):
        _store(tmp_path).register("short@example.com", "tooshort1")


def test_should_reject_a_malformed_email(tmp_path: Path) -> None:
    with pytest.raises(AccountError):
        _store(tmp_path).register("not-an-email", STRONG_PASSWORD)


def test_should_reject_registering_the_same_email_twice(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register("dup@example.com", STRONG_PASSWORD)
    with pytest.raises(EmailAlreadyRegisteredError):
        store.register("dup@example.com", STRONG_PASSWORD)


def test_should_treat_email_case_and_whitespace_as_equivalent_for_uniqueness(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.register("Case@Example.com", STRONG_PASSWORD)
    with pytest.raises(EmailAlreadyRegisteredError):
        store.register("  case@example.com  ", STRONG_PASSWORD)


def test_should_authenticate_a_registered_user_with_the_right_password(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register("user@example.com", STRONG_PASSWORD)
    account = store.authenticate("user@example.com", STRONG_PASSWORD)
    assert account is not None
    assert account.email == "user@example.com"


def test_should_refuse_authentication_with_the_wrong_password(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register("user@example.com", STRONG_PASSWORD)
    assert store.authenticate("user@example.com", "wrong-password-entirely") is None


def test_should_refuse_authentication_for_an_unregistered_email(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.authenticate("nobody@example.com", STRONG_PASSWORD) is None


def test_should_refuse_authentication_for_a_disabled_account(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    store = AccountStore(db_path)
    account = store.register("user@example.com", STRONG_PASSWORD)
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE users SET is_disabled = 1 WHERE id = ?", (account.id,))
    connection.commit()
    connection.close()
    assert store.authenticate("user@example.com", STRONG_PASSWORD) is None


def test_should_never_store_the_plaintext_password(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    AccountStore(db_path).register("user@example.com", STRONG_PASSWORD)
    raw = db_path.read_bytes()
    assert STRONG_PASSWORD.encode() not in raw


def test_should_look_up_an_account_by_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = store.register("user@example.com", STRONG_PASSWORD)
    found = store.get_by_id(created.id)
    assert found is not None
    assert found.email == "user@example.com"


def test_should_report_is_disabled_true_for_a_disabled_account(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    store = AccountStore(db_path)
    account = store.register("user@example.com", STRONG_PASSWORD)
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE users SET is_disabled = 1 WHERE id = ?", (account.id,))
    connection.commit()
    connection.close()
    found = store.get_by_id(account.id)
    assert found is not None
    assert found.is_disabled is True


def test_should_return_none_for_an_unknown_account_id(tmp_path: Path) -> None:
    assert _store(tmp_path).get_by_id(999) is None

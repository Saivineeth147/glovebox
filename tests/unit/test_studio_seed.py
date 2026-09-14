"""Seeding exists so a fresh clone can sign in; it must never be a way back to admin."""

from __future__ import annotations

from pathlib import Path

import pytest

from glovebox.studio.accounts import AccountStore, Role, WeakPasswordError
from glovebox.studio.seed import EMAIL_VARIABLE, PASSWORD_VARIABLE, seed_administrator

CONFIGURED_EMAIL = "admin@glovebox.local"
CONFIGURED_PASSWORD = "glovebox-admin-2026"


def _configure(monkeypatch: pytest.MonkeyPatch, email: str, password: str) -> None:
    monkeypatch.setenv(EMAIL_VARIABLE, email)
    monkeypatch.setenv(PASSWORD_VARIABLE, password)


def test_should_create_an_administrator_when_configured_and_the_database_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, CONFIGURED_EMAIL, CONFIGURED_PASSWORD)
    store = AccountStore(tmp_path / "studio.db")

    account = seed_administrator(store)

    assert account is not None
    assert (account.email, account.role) == (CONFIGURED_EMAIL, Role.ADMIN)


def test_should_seed_an_account_that_can_actually_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, CONFIGURED_EMAIL, CONFIGURED_PASSWORD)
    store = AccountStore(tmp_path / "studio.db")
    seed_administrator(store)

    assert store.authenticate(CONFIGURED_EMAIL, CONFIGURED_PASSWORD) is not None


def test_should_do_nothing_when_the_variables_are_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(EMAIL_VARIABLE, raising=False)
    monkeypatch.delenv(PASSWORD_VARIABLE, raising=False)
    store = AccountStore(tmp_path / "studio.db")

    assert seed_administrator(store) is None
    assert store.list_accounts() == []


def test_should_refuse_to_seed_once_any_account_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard that stops a demo convenience from re-granting admin after a demotion."""
    _configure(monkeypatch, CONFIGURED_EMAIL, CONFIGURED_PASSWORD)
    store = AccountStore(tmp_path / "studio.db")
    store.register("someone@example.com", "a-long-enough-password")

    assert seed_administrator(store) is None
    assert [account.email for account in store.list_accounts()] == ["someone@example.com"]


def test_should_raise_rather_than_silently_skip_a_password_that_is_too_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An un-seeded Studio and a mistyped password look identical from the sign-in form."""
    _configure(monkeypatch, CONFIGURED_EMAIL, "short")
    store = AccountStore(tmp_path / "studio.db")

    with pytest.raises(WeakPasswordError):
        seed_administrator(store)

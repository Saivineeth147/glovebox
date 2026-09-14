"""Create the first Studio administrator from the environment.

A reviewer cloning this repository should not have to guess their way past a sign-in form,
so a configured account is created on an empty database and the README can name the
credentials. It is refused the moment any account exists, which is what keeps a convenience
for demos from becoming a way to re-grant admin on a real install after a demotion.
"""

from __future__ import annotations

import os

from glovebox.studio.accounts import Account, AccountStore

EMAIL_VARIABLE = "GLOVEBOX_STUDIO_EMAIL"
PASSWORD_VARIABLE = "GLOVEBOX_STUDIO_PASSWORD"  # noqa: S105 — a variable name, not a secret


def seed_administrator(store: AccountStore) -> Account | None:
    """Register the configured administrator, or return None when seeding does not apply.

    Returns None when the variables are unset (the operator wants the sign-up form) or when
    an account already exists. A weak or malformed value raises out of `register` rather than
    being swallowed: a silently un-seeded Studio looks identical to a broken password.
    """
    email = os.environ.get(EMAIL_VARIABLE, "").strip()
    password = os.environ.get(PASSWORD_VARIABLE, "")
    if not email or not password:
        return None
    if store.list_accounts():
        return None
    return store.register(email, password)

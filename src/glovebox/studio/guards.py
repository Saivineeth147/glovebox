"""FastAPI dependencies that gate `/api/*` routes on an authenticated session.

Why dependencies rather than middleware: role requirements differ per route (`admin`
only for capability approval, `operator` for the mutating actions, any signed-in role
for reads), and FastAPI's dependency injection already expresses per-route request
data throughout this codebase (see server.py's Body models) -- this is the same
mechanism, not a second one.

Role checks treat the three roles as a ladder (admin > operator > viewer): the
task defines them as an ordered escalation of trust, and an admin who could not also
do what an operator does would be unable to act on their own Studio instance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request

from .accounts import Account, AccountStore, Role
from .sessions import SESSION_COOKIE_NAME, SessionStore

UNAUTHENTICATED_MESSAGE = "authentication required"
FORBIDDEN_MESSAGE = "insufficient role"
ROLE_RANK = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


def _stores(request: Request) -> tuple[AccountStore, SessionStore]:
    return request.app.state.account_store, request.app.state.session_store


def get_current_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Account | None:
    """Resolve the session cookie to an account, or None if not signed in.

    Never raises: callers that require a user use `require_user`, but a route like
    the SPA shell can accept an optional identity without a 401.
    """
    if session_token is None:
        return None
    accounts, sessions = _stores(request)
    user_id = sessions.resolve(session_token)
    if user_id is None:
        return None
    account = accounts.get_by_id(user_id)
    return None if account is None or account.is_disabled else account


def require_user(user: Annotated[Account | None, Depends(get_current_user)]) -> Account:
    if user is None:
        raise HTTPException(status_code=401, detail=UNAUTHENTICATED_MESSAGE)
    return user


def require_role(minimum_role: Role | str) -> Callable[..., Account]:
    """Build a dependency that also requires at least `minimum_role` on the ladder."""
    required = Role(minimum_role)

    def _dependency(user: Annotated[Account, Depends(require_user)]) -> Account:
        if ROLE_RANK[user.role] < ROLE_RANK[required]:
            raise HTTPException(status_code=403, detail=FORBIDDEN_MESSAGE)
        return user

    return _dependency

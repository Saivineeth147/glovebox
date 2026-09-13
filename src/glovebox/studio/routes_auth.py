"""Auth endpoints: register, login, logout, and the identity check the SPA polls.

Login answers an unknown email exactly like a wrong password -- both a 401 with the
same body -- so a caller cannot enumerate registered accounts through this endpoint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .accounts import (
    Account,
    AccountError,
    AccountStore,
    EmailAlreadyRegisteredError,
    WeakPasswordError,
)
from .guards import require_user
from .sessions import SESSION_COOKIE_NAME, SESSION_LIFETIME_HOURS, SessionStore
from .throttle import TooManyAttempts

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_CREDENTIALS_MESSAGE = "invalid email or password"
EMAIL_ALREADY_REGISTERED_MESSAGE = "email already registered"
SESSION_COOKIE_MAX_AGE_SECONDS = SESSION_LIFETIME_HOURS * 60 * 60


class RegisterBody(BaseModel):
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


def _stores(request: Request) -> tuple[AccountStore, SessionStore]:
    return request.app.state.account_store, request.app.state.session_store


def _account_public(account: Account) -> dict[str, str]:
    return {"email": account.email, "role": account.role.value}


def _start_session(response: Response, sessions: SessionStore, user_id: int) -> None:
    session = sessions.create(user_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
    )


@router.post("/register")
def register(body: RegisterBody, request: Request, response: Response) -> dict[str, str]:
    accounts, sessions = _stores(request)
    try:
        account = accounts.register(body.email, body.password)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=409, detail=EMAIL_ALREADY_REGISTERED_MESSAGE) from exc
    except WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _start_session(response, sessions, account.id)
    return _account_public(account)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, str]:
    accounts, sessions = _stores(request)
    limiter = request.app.state.login_limiter
    identity = body.email.strip().lower()
    try:
        limiter.check(identity)
    except TooManyAttempts as blocked:
        # 429 rather than 401: the caller is being throttled, not told anything about the
        # account, and Retry-After is the honest way to say for how long.
        raise HTTPException(
            status_code=429,
            detail=str(blocked),
            headers={"Retry-After": str(blocked.retry_after_seconds)},
        ) from blocked
    account = accounts.authenticate(body.email, body.password)
    if account is None:
        limiter.record_failure(identity)
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_MESSAGE)
    limiter.clear(identity)
    _start_session(response, sessions, account.id)
    return _account_public(account)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    _, sessions = _stores(request)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is not None:
        sessions.delete(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: Annotated[Account, Depends(require_user)]) -> dict[str, str]:
    return _account_public(user)

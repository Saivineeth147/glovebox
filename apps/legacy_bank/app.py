"""Meridian Core — hostile legacy back-office web app used as the Glovebox proxy target.

Design notes (why it looks the way it does):
* A frameset (`/t/{tenant}/`) with nav/menu/main frames — automation must address frames.
* Table-based layouts, `<font>` tags, no `id`/`data-testid` attributes anywhere.
* Server-rendered forms with `name` attributes only, JS `confirm()` before a mutating submit.
* Two tenants share the code but differ in branding, labels, and an extra interstitial —
  a stand-in for "same vendor product, configured differently per institution".
* A fault injector (`/__sim/faults`) arms one-shot runtime faults. It is a simulation control
  surface for tests and evidence, and is *not* something the agent is allowed to touch
  (the policy allowlist excludes it).
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .data import FAULTS, MEMBERS, PRODUCTS, next_reference

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

TENANTS: dict[str, dict[str, Any]] = {
    "alpha": {
        "name": "Meridian Core — Alpine Credit Union",
        "color": "#1f3a5f",
        "member_label": "Member No.",
        "search_button": "Find Member",
        "post_login_notice": None,
        "version": "7.2.1",
    },
    "bravo": {
        "name": "Meridian Core — Bayview Federal CU",
        "color": "#5f1f2e",
        "member_label": "Member Number",
        "search_button": "Search",
        "post_login_notice": "Scheduled maintenance Sunday 02:00-04:00 ET. Click Acknowledge to continue.",
        "version": "7.4.0",
    },
}

SESSION_COOKIE = "MCSESSION"
_sessions: dict[str, dict[str, Any]] = {}


def _username() -> str:
    return os.environ.get("GLOVEBOX_APP_USERNAME", "teller1")


def _password() -> str:
    return os.environ.get("GLOVEBOX_APP_PASSWORD", "teller1-pass")


def _session(request: Request) -> dict[str, Any] | None:
    sid = request.cookies.get(SESSION_COOKIE)
    return _sessions.get(sid) if sid else None


def _render(request: Request, name: str, tenant: str, **ctx: Any) -> HTMLResponse:
    t = TENANTS[tenant]
    return TEMPLATES.TemplateResponse(
        request, name, {"tenant": tenant, "t": t, "base": f"/t/{tenant}", **ctx}
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Meridian Core (simulated legacy back-office)", docs_url=None)

    # ---------------------------------------------------------------- simulation controls
    @app.get("/__sim/faults")
    def list_faults() -> JSONResponse:
        return JSONResponse({"armed": FAULTS.armed(), "known": sorted(FAULTS.KNOWN)})

    @app.post("/__sim/faults/{name}")
    def arm_fault(name: str, remaining: int = 1) -> JSONResponse:
        FAULTS.arm(name, remaining)
        return JSONResponse({"armed": FAULTS.armed()})

    @app.delete("/__sim/faults")
    def clear_faults() -> JSONResponse:
        FAULTS.clear()
        return JSONResponse({"armed": {}})

    @app.get("/__sim/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    # ---------------------------------------------------------------- shell
    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/t/alpha/")

    @app.get("/t/{tenant}/", response_class=HTMLResponse)
    def frameset(request: Request, tenant: str) -> HTMLResponse:
        return _render(request, "frameset.html", tenant)

    @app.get("/t/{tenant}/nav", response_class=HTMLResponse)
    def nav(request: Request, tenant: str) -> HTMLResponse:
        return _render(request, "nav.html", tenant, session=_session(request))

    @app.get("/t/{tenant}/menu", response_class=HTMLResponse)
    def menu(request: Request, tenant: str) -> HTMLResponse:
        return _render(request, "menu.html", tenant, session=_session(request))

    # ---------------------------------------------------------------- auth
    @app.get("/t/{tenant}/app/login", response_class=HTMLResponse)
    def login_form(request: Request, tenant: str, msg: str = "") -> HTMLResponse:
        return _render(request, "login.html", tenant, msg=msg)

    @app.post("/t/{tenant}/app/login")
    def login(
        request: Request, tenant: str, username: str = Form(""), password: str = Form("")
    ) -> Response:
        if username != _username() or password != _password():
            return _render(request, "login.html", tenant, msg="Invalid operator credentials.")
        sid = secrets.token_hex(16)
        _sessions[sid] = {"user": username, "role": "teller", "tenant": tenant}
        target = f"/t/{tenant}/app/notice" if TENANTS[tenant]["post_login_notice"] else f"/t/{tenant}/app/home"
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True)
        return resp

    @app.get("/t/{tenant}/app/notice", response_class=HTMLResponse)
    def notice(request: Request, tenant: str) -> HTMLResponse:
        return _render(request, "notice.html", tenant, text=TENANTS[tenant]["post_login_notice"])

    @app.post("/t/{tenant}/app/notice")
    def ack_notice(tenant: str) -> RedirectResponse:
        return RedirectResponse(f"/t/{tenant}/app/home", status_code=303)

    @app.get("/t/{tenant}/app/logout")
    def logout(request: Request, tenant: str) -> RedirectResponse:
        sid = request.cookies.get(SESSION_COOKIE)
        if sid:
            _sessions.pop(sid, None)
        resp = RedirectResponse(f"/t/{tenant}/app/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # ---------------------------------------------------------------- guarded pages
    async def _guard(request: Request, tenant: str) -> Response | None:
        """Apply cross-cutting runtime faults, then require a session."""
        if FAULTS.consume("app_error"):
            return HTMLResponse(
                TEMPLATES.get_template("error.html").render(t=TENANTS[tenant], base=f"/t/{tenant}"),
                status_code=500,
            )
        if FAULTS.consume("slow"):
            await asyncio.sleep(4.0)
        if FAULTS.consume("session_expired"):
            sid = request.cookies.get(SESSION_COOKIE)
            if sid:
                _sessions.pop(sid, None)
            return RedirectResponse(
                f"/t/{tenant}/app/login?msg=Your+session+has+expired.+Please+sign+in+again.",
                status_code=303,
            )
        if _session(request) is None:
            return RedirectResponse(f"/t/{tenant}/app/login", status_code=303)
        return None

    @app.get("/t/{tenant}/app/home", response_class=HTMLResponse)
    async def home(request: Request, tenant: str) -> Response:
        if (r := await _guard(request, tenant)) is not None:
            return r
        return _render(request, "home.html", tenant, session=_session(request))

    @app.get("/t/{tenant}/app/members/search", response_class=HTMLResponse)
    async def member_search(request: Request, tenant: str, msg: str = "") -> Response:
        if (r := await _guard(request, tenant)) is not None:
            return r
        return _render(
            request,
            "member_search.html",
            tenant,
            msg=msg,
            interstitial=FAULTS.consume("interstitial"),
        )

    @app.post("/t/{tenant}/app/members/search")
    async def member_search_submit(
        request: Request, tenant: str, member_no: str = Form("")
    ) -> Response:
        if (r := await _guard(request, tenant)) is not None:
            return r
        member_no = member_no.strip()
        if not member_no.isdigit():
            return _render(
                request,
                "member_search.html",
                tenant,
                msg="",
                field_error="Member number must be numeric.",
                interstitial=False,
            )
        if member_no not in MEMBERS:
            return _render(request, "member_not_found.html", tenant, member_no=member_no)
        return RedirectResponse(f"/t/{tenant}/app/members/{member_no}", status_code=303)

    @app.get("/t/{tenant}/app/members/{member_id}", response_class=HTMLResponse)
    async def member_detail(request: Request, tenant: str, member_id: str) -> Response:
        if (r := await _guard(request, tenant)) is not None:
            return r
        m = MEMBERS.get(member_id)
        if m is None:
            return _render(request, "member_not_found.html", tenant, member_no=member_id)
        return _render(request, "member_detail.html", tenant, m=m)

    @app.get("/t/{tenant}/app/members/{member_id}/subaccount/new", response_class=HTMLResponse)
    async def subaccount_form(request: Request, tenant: str, member_id: str) -> Response:
        if (r := await _guard(request, tenant)) is not None:
            return r
        m = MEMBERS.get(member_id)
        if m is None:
            return _render(request, "member_not_found.html", tenant, member_no=member_id)
        return _render(request, "subaccount_new.html", tenant, m=m, products=PRODUCTS, error="")

    @app.post("/t/{tenant}/app/members/{member_id}/subaccount/new")
    async def subaccount_submit(
        request: Request,
        tenant: str,
        member_id: str,
        product: str = Form(""),
        nickname: str = Form(""),
        initial_deposit: str = Form("0"),
    ) -> Response:
        if (r := await _guard(request, tenant)) is not None:
            return r
        m = MEMBERS.get(member_id)
        if m is None:
            return _render(request, "member_not_found.html", tenant, member_no=member_id)
        if m.status == "Legal hold" or FAULTS.consume("permission_denied"):
            return _render(request, "permission_denied.html", tenant, m=m)
        error = ""
        if product not in PRODUCTS:
            error = "Select a valid product."
        elif not nickname.strip() or FAULTS.consume("validation"):
            error = "Nickname is required and must be 3-20 characters."
        else:
            try:
                dep = float(initial_deposit or "0")
            except ValueError:
                dep = -1
            if dep < 0:
                error = "Initial deposit must be a non-negative amount."
        if error:
            return _render(
                request, "subaccount_new.html", tenant, m=m, products=PRODUCTS, error=error
            )
        ref = next_reference()
        m.sub_accounts.append({"ref": ref, "product": product, "nickname": nickname.strip()})
        return _render(
            request, "subaccount_confirm.html", tenant, m=m, ref=ref, product=product, nickname=nickname
        )

    return app

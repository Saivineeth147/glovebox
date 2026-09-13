"""Glovebox Studio API and static host.

    glovebox studio --port 8800

Serves the built single-page app from `studio/static` and a JSON API over the job manager,
the run directory, the catalog and the policy. Operator takeover goes through the same
`OperatorBridge` the CLI console uses — the UI is a client of the control model, not a
second implementation of it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from glovebox.agent.llm import RECOMMENDED_MODELS, available_provider
from glovebox.catalog import Catalog
from glovebox.catalog.registry import UnverifiedOutcomeError
from glovebox.schema.capability import Capability
from glovebox.schema.policy import Policy

from .accounts import Account, AccountStore, Role
from .guards import require_role, require_user
from .health import replay_health
from .jobs import JobManager
from .routes_auth import router as auth_router
from .sessions import SessionStore
from .throttle import AttemptLimiter

STATIC = Path(__file__).parent / "static"
STUDIO_DB_ENV_VAR = "GLOVEBOX_STUDIO_DB"
DEFAULT_DB_FILENAME = "studio.db"
API_PATH_PREFIX = "api/"
UNKNOWN_API_ROUTE_MESSAGE = "not found"


def _resolve_db_path(runs_dir: Path) -> Path:
    override = os.environ.get(STUDIO_DB_ENV_VAR)
    db_path = Path(override) if override else runs_dir / DEFAULT_DB_FILENAME
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


class DiscoverBody(BaseModel):
    goal: str
    app_url: str
    capability_id: str
    params: dict[str, str] = {}
    tenant: str = "alpha"
    offline: str | None = None
    model: str | None = None


class ReplayBody(BaseModel):
    capability_id: str
    params: dict[str, Any] = {}
    tenant: str | None = None
    attended: bool = True
    allow_draft: bool = False
    faults: list[str] = []


class RoleBody(BaseModel):
    role: Role


class ApproveBody(BaseModel):
    # No reviewer field: approval is recorded against the signed-in admin, because a
    # name typed into the request is not an audit trail.
    notes: str | None = None
    # The reviewer saw the warning on the capability page and chose to proceed.
    accept_unverified: bool = False


class CommandBody(BaseModel):
    op: str
    ref: str | None = None
    text: str | None = None
    option: str | None = None
    key: str | None = None
    url: str | None = None
    note: str | None = None


def create_studio(runs_dir: Path, catalog_dir: Path, policy_path: Path) -> FastAPI:
    app = FastAPI(title="Glovebox Studio", docs_url="/api/docs")
    jobs = JobManager(runs_dir, catalog_dir, policy_path)
    catalog = Catalog(catalog_dir)

    db_path = _resolve_db_path(runs_dir)
    app.state.login_limiter = AttemptLimiter()
    app.state.account_store = AccountStore(db_path)
    app.state.session_store = SessionStore(db_path)
    app.state.jobs = jobs
    app.include_router(auth_router)

    # Every route below requires a signed-in session; mutating and admin-only routes
    # layer `require_role` on top (see the per-route `dependencies=` below).
    api = APIRouter(dependencies=[Depends(require_user)])

    def policy() -> Policy:
        return Policy.load(policy_path)

    def target_base() -> str:
        return policy().allowed_origins[0]

    # ------------------------------------------------------------------ overview
    @api.get("/api/overview")
    def overview() -> dict[str, Any]:
        runs = jobs.runs()
        caps = catalog.all()
        health = replay_health(runs, {c.id: c.version for c in caps})
        try:
            t = httpx.get(f"{target_base()}/__sim/faults", timeout=1.5).json()
            target = {"up": True, "armed": t.get("armed", {}), "known": t.get("known", [])}
        except httpx.HTTPError:
            target = {"up": False, "armed": {}, "known": []}
        return {
            "runs": len(runs),
            "replays": health.eligible,
            "replay_success_rate": health.rate,
            "replay_health": {
                "answered": health.answered,
                "eligible": health.eligible,
                "superseded": health.superseded,
                "refused": health.refused,
            },
            "capabilities": len(caps),
            "approved": sum(1 for c in caps if c.review.status == "approved"),
            "open_interventions": sum(1 for j in jobs.all() if j.bridge.current),
            "target": {**target, "url": target_base()},
            "policy": policy().name,
            "model": os.environ.get("GLOVEBOX_MODEL")
            or (
                "claude-opus-5"
                if available_provider() == "anthropic"
                else "anthropic/claude-sonnet-4.5"
            ),
            "provider": available_provider(),
            "has_api_key": available_provider() is not None,
            "models": [m for m in RECOMMENDED_MODELS if m["provider"] == available_provider()],
            "recent": runs[:6],
        }

    # ------------------------------------------------------------------ runs
    @api.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return jobs.runs()

    @api.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        if not (runs_dir / run_id).exists():
            raise HTTPException(404, "no such run")
        s = jobs.run_summary(run_id)
        s["events_list"] = list(jobs.events(run_id))
        d = runs_dir / run_id
        s["files"] = {
            "screenshots": sorted(p.name for p in (d / "screenshots").glob("*.png"))
            if (d / "screenshots").exists()
            else [],
            "snapshots": sorted(p.name for p in (d / "snapshots").glob("*.html"))
            if (d / "snapshots").exists()
            else [],
            "transcript": (d / "transcript.json").exists(),
            "capability": (d / "capability.json").exists(),
        }
        return s

    @api.get("/api/runs/{run_id}/stream")
    def stream_run(run_id: str) -> StreamingResponse:
        return StreamingResponse(
            jobs.stream(run_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/api/runs/{run_id}/files/{path:path}")
    def run_file(run_id: str, path: str) -> Any:
        p = jobs.artifact(run_id, path)
        if p is None:
            raise HTTPException(404, "no such file")
        return FileResponse(str(p))

    # ------------------------------------------------------------------ capabilities
    def cap_public(c: Capability) -> dict[str, Any]:
        d = c.model_dump(mode="json")
        d["confidence"] = c.review.confidence
        return d

    @api.get("/api/capabilities")
    def list_caps() -> list[dict[str, Any]]:
        return [cap_public(c) for c in catalog.all()]

    @api.get("/api/capabilities/tools")
    def cap_tools(include_drafts: bool = True) -> list[dict[str, Any]]:
        return catalog.tool_definitions(include_drafts)

    @api.get("/api/capabilities/{cap_id}")
    def get_cap(cap_id: str) -> dict[str, Any]:
        try:
            return cap_public(catalog.load(cap_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @api.post("/api/capabilities/{cap_id}/approve")
    def approve(
        cap_id: str,
        body: ApproveBody,
        user: Annotated[Account, Depends(require_role("admin"))],
    ) -> dict[str, Any]:
        try:
            approved = catalog.approve(
                cap_id, user.email, body.notes, accept_unverified=body.accept_unverified
            )
        except UnverifiedOutcomeError as refusal:
            raise HTTPException(status_code=409, detail=str(refusal)) from refusal
        return cap_public(approved)

    # ------------------------------------------------------------------ jobs
    @api.post("/api/discover", dependencies=[Depends(require_role("operator"))])
    def discover(body: DiscoverBody) -> dict[str, Any]:
        job = jobs.start_discovery(
            body.goal,
            body.app_url,
            body.capability_id,
            body.params,
            body.tenant,
            body.offline,
            body.model,
        )
        return job.public()

    @api.post("/api/replay", dependencies=[Depends(require_role("operator"))])
    def replay(body: ReplayBody) -> dict[str, Any]:
        try:
            job = jobs.start_replay(
                body.capability_id,
                body.params,
                body.tenant,
                body.attended,
                body.allow_draft,
                body.faults,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return job.public()

    @api.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [j.public() for j in jobs.all()]

    @api.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return jobs.get(job_id).public()
        except KeyError as exc:
            raise HTTPException(404, "no such job") from exc

    # ------------------------------------------------------------------ operator (takeover)
    @api.get("/api/jobs/{job_id}/operator")
    def operator_state(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        obs = job.bridge.last_observation
        cur = job.bridge.current
        return {
            "owner": "human" if cur else "automation",
            "intervention": cur.model_dump(mode="json", exclude={"observation_summary"})
            if cur
            else None,
            "url": obs.url if obs else None,
            "screenshot": f"/api/jobs/{job_id}/operator/screenshot?t={int(obs.screenshot.stat().st_mtime_ns)}"
            if obs and obs.screenshot and obs.screenshot.exists()
            else None,
            "viewport": list(obs.viewport) if obs else None,
            "elements": [
                {
                    "ref": e.ref,
                    "role": e.role,
                    "name": e.name,
                    "label": e.label,
                    "text": e.text[:80],
                    "name_attr": e.name_attr,
                    "frame": "/".join(e.frame),
                    "box": list(e.page_box),
                    "options": e.options,
                }
                for e in obs.elements
                if e.interactive
            ]
            if obs
            else [],
            "actions": cur.human_actions if cur else [],
            "history": [
                i.model_dump(mode="json", exclude={"observation_summary", "human_actions"})
                for i in job.bridge.history
            ],
        }

    @api.get("/api/jobs/{job_id}/operator/screenshot")
    def operator_shot(job_id: str) -> Any:
        obs = jobs.get(job_id).bridge.last_observation
        if obs and obs.screenshot and obs.screenshot.exists():
            return FileResponse(str(obs.screenshot), media_type="image/png")
        raise HTTPException(404, "no screenshot")

    @api.post(
        "/api/jobs/{job_id}/operator/command", dependencies=[Depends(require_role("operator"))]
    )
    def operator_cmd(
        job_id: str, body: CommandBody, user: Annotated[Account, Depends(require_user)]
    ) -> dict[str, Any]:
        # The operator identity for the audit trail comes from the authenticated
        # session, never from the request body -- a client cannot self-declare who
        # performed a takeover action.
        job = jobs.get(job_id)
        args = {k: v for k, v in body.model_dump().items() if k != "op" and v not in (None, "")}
        return job.bridge.submit(body.op, operator=user.email, **args)

    # ------------------------------------------------------------------ policy + target
    # ------------------------------------------------------------------ operators
    @api.get("/api/users", dependencies=[Depends(require_role("admin"))])
    def list_users() -> list[dict[str, Any]]:
        accounts = app.state.account_store.list_accounts()
        return [{"email": a.email, "role": a.role.value} for a in accounts]

    @api.post("/api/users/{email}/role", dependencies=[Depends(require_role("admin"))])
    def set_user_role(email: str, body: RoleBody) -> dict[str, Any]:
        account = app.state.account_store.set_role(email, body.role)
        if account is None:
            raise HTTPException(status_code=404, detail=f"no account for {email}")
        return {"email": account.email, "role": account.role.value}

    @api.get("/api/policy")
    def get_policy() -> dict[str, Any]:
        return {
            "policy": policy().model_dump(mode="json"),
            "raw": policy_path.read_text(encoding="utf-8"),
            "path": str(policy_path),
        }

    @api.post("/api/target/faults/{name}", dependencies=[Depends(require_role("operator"))])
    def arm_fault(name: str) -> dict[str, Any]:
        r = httpx.post(f"{target_base()}/__sim/faults/{name}", timeout=3)
        return dict(r.json())

    @api.delete("/api/target/faults", dependencies=[Depends(require_role("operator"))])
    def clear_faults() -> dict[str, Any]:
        return dict(httpx.delete(f"{target_base()}/__sim/faults", timeout=3).json())

    app.include_router(api)

    # ------------------------------------------------------------------ static SPA
    if (STATIC / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(STATIC / "assets")), name="assets")

    @app.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
    def spa(path: str) -> Any:
        if path.startswith(API_PATH_PREFIX):
            return JSONResponse({"detail": UNKNOWN_API_ROUTE_MESSAGE}, status_code=404)
        # Resolve before serving: this route is deliberately unauthenticated so the sign-in
        # screen can load, so it must not be able to reach outside the built bundle. Uvicorn
        # normalises traversal today, but that is the server's behaviour, not this app's.
        candidate = (STATIC / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(STATIC.resolve()):
            return FileResponse(str(candidate))
        index = STATIC / "index.html"
        if not index.exists():
            return HTMLResponse(
                "<h1>Glovebox Studio</h1><p>UI not built. Run <code>make ui</code>.</p>",
                status_code=503,
            )
        return FileResponse(str(index))

    return app

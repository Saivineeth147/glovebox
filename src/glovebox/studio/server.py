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
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from glovebox.agent.llm import available_provider
from glovebox.catalog import Catalog
from glovebox.schema.capability import Capability
from glovebox.schema.policy import Policy

from .jobs import JobManager

STATIC = Path(__file__).parent / "static"


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


class ApproveBody(BaseModel):
    reviewer: str
    notes: str | None = None


class CommandBody(BaseModel):
    op: str
    operator: str = "studio-user"
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

    def policy() -> Policy:
        return Policy.load(policy_path)

    def target_base() -> str:
        return policy().allowed_origins[0]

    # ------------------------------------------------------------------ overview
    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        runs = jobs.runs()
        caps = catalog.all()
        replays = [r for r in runs if r["kind"] == "replay" and r["status"] != "running"]
        ok = sum(1 for r in replays if r["status"] == "success")
        try:
            t = httpx.get(f"{target_base()}/__sim/faults", timeout=1.5).json()
            target = {"up": True, "armed": t.get("armed", {}), "known": t.get("known", [])}
        except httpx.HTTPError:
            target = {"up": False, "armed": {}, "known": []}
        return {
            "runs": len(runs),
            "replays": len(replays),
            "replay_success_rate": (ok / len(replays)) if replays else None,
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
            "recent": runs[:6],
        }

    # ------------------------------------------------------------------ runs
    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return jobs.runs()

    @app.get("/api/runs/{run_id}")
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

    @app.get("/api/runs/{run_id}/stream")
    def stream_run(run_id: str) -> StreamingResponse:
        return StreamingResponse(
            jobs.stream(run_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/files/{path:path}")
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

    @app.get("/api/capabilities")
    def list_caps() -> list[dict[str, Any]]:
        return [cap_public(c) for c in catalog.all()]

    @app.get("/api/capabilities/tools")
    def cap_tools(include_drafts: bool = True) -> list[dict[str, Any]]:
        return catalog.tool_definitions(include_drafts)

    @app.get("/api/capabilities/{cap_id}")
    def get_cap(cap_id: str) -> dict[str, Any]:
        try:
            return cap_public(catalog.load(cap_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/capabilities/{cap_id}/approve")
    def approve(cap_id: str, body: ApproveBody) -> dict[str, Any]:
        return cap_public(catalog.approve(cap_id, body.reviewer, body.notes))

    # ------------------------------------------------------------------ jobs
    @app.post("/api/discover")
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

    @app.post("/api/replay")
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

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [j.public() for j in jobs.all()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return jobs.get(job_id).public()
        except KeyError as exc:
            raise HTTPException(404, "no such job") from exc

    # ------------------------------------------------------------------ operator (takeover)
    @app.get("/api/jobs/{job_id}/operator")
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

    @app.get("/api/jobs/{job_id}/operator/screenshot")
    def operator_shot(job_id: str) -> Any:
        obs = jobs.get(job_id).bridge.last_observation
        if obs and obs.screenshot and obs.screenshot.exists():
            return FileResponse(str(obs.screenshot), media_type="image/png")
        raise HTTPException(404, "no screenshot")

    @app.post("/api/jobs/{job_id}/operator/command")
    def operator_cmd(job_id: str, body: CommandBody) -> dict[str, Any]:
        job = jobs.get(job_id)
        args = {
            k: v
            for k, v in body.model_dump().items()
            if k not in {"op", "operator"} and v not in (None, "")
        }
        return job.bridge.submit(body.op, operator=body.operator, **args)

    # ------------------------------------------------------------------ policy + target
    @app.get("/api/policy")
    def get_policy() -> dict[str, Any]:
        return {
            "policy": policy().model_dump(mode="json"),
            "raw": policy_path.read_text(encoding="utf-8"),
            "path": str(policy_path),
        }

    @app.post("/api/target/faults/{name}")
    def arm_fault(name: str) -> dict[str, Any]:
        r = httpx.post(f"{target_base()}/__sim/faults/{name}", timeout=3)
        return dict(r.json())

    @app.delete("/api/target/faults")
    def clear_faults() -> dict[str, Any]:
        return dict(httpx.delete(f"{target_base()}/__sim/faults", timeout=3).json())

    # ------------------------------------------------------------------ static SPA
    if (STATIC / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(STATIC / "assets")), name="assets")

    @app.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
    def spa(path: str) -> Any:
        f = STATIC / path
        if path and f.is_file():
            return FileResponse(str(f))
        index = STATIC / "index.html"
        if not index.exists():
            return HTMLResponse(
                "<h1>Glovebox Studio</h1><p>UI not built. Run <code>make ui</code>.</p>",
                status_code=503,
            )
        return FileResponse(str(index))

    return app

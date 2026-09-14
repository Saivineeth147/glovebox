"""Background jobs for Studio: each discovery or replay runs on its own thread with its own
Playwright instance, run directory and operator bridge. The API reads the run's events.jsonl
for history and streams new lines for live views, so the UI never touches the browser thread."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from glovebox.control.session import OperatorBridge
from glovebox.schema.capability import Parameter, ParamType
from glovebox.schema.policy import Policy


@dataclass
class Job:
    id: str
    kind: str  # discovery | replay
    title: str
    params: dict[str, Any]
    bridge: OperatorBridge
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "queued"  # queued | running | finished | error
    run_id: str | None = None
    run_dir: Path | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    thread: threading.Thread | None = None
    #: Set by `JobManager.cancel`. A daemon thread cannot be killed from outside, so the
    #: run loops ask this between steps and stop themselves.
    cancel: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict[str, Any]:
        cur = self.bridge.current
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "params": {k: ("••••" if k in {"password"} else v) for k, v in self.params.items()},
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "cancel_requested": self.cancel.is_set(),
            "run_id": self.run_id,
            "result": self.result,
            "error": self.error,
            "owner": "human" if cur else "automation",
            "intervention": cur.model_dump(mode="json", exclude={"observation_summary"})
            if cur
            else None,
        }


class JobManager:
    def __init__(self, runs_dir: Path, catalog_dir: Path, policy_path: Path) -> None:
        self.runs_dir = runs_dir
        self.catalog_dir = catalog_dir
        self.policy_path = policy_path
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ launch
    def _creds(self) -> dict[str, str]:
        return {
            "username": os.environ.get("GLOVEBOX_APP_USERNAME", "teller1"),
            "password": os.environ.get("GLOVEBOX_APP_PASSWORD", "teller1-pass"),
        }

    def start_discovery(
        self,
        goal: str,
        app_url: str,
        capability_id: str,
        params: dict[str, str],
        tenant: str = "alpha",
        offline: str | None = None,
        model: str | None = None,
    ) -> Job:
        job = Job(
            id=f"job_{uuid.uuid4().hex[:8]}",
            kind="discovery",
            title=goal,
            params=params,
            bridge=OperatorBridge(),
        )

        def run() -> None:
            from glovebox.agent.scripts import SCRIPTS, standard_params
            from glovebox.catalog import Catalog
            from glovebox.runner import run_discovery

            try:
                job.status = "running"
                policy = Policy.load(self.policy_path)
                std = standard_params(app_url)
                specs = [
                    *std["specs"],
                    *[
                        Parameter(name=k, type=ParamType.STRING, description=f"Input parameter {k}")
                        for k in params
                    ],
                ]
                values = {**std["values"], **params}
                if offline:
                    from glovebox.agent.llm import ScriptedLLM

                    script = SCRIPTS[offline]

                    def factory(obs: Any) -> Any:
                        return ScriptedLLM(script, obs)
                else:
                    from glovebox.agent.llm import make_llm

                    llm = make_llm(model)

                    def factory(obs: Any) -> Any:
                        return llm

                def on_ctx(run_id: str, run_dir: Path) -> None:
                    job.run_id, job.run_dir = run_id, run_dir

                res = run_discovery(
                    goal=goal,
                    entry_url=app_url.rstrip("/") + f"/t/{tenant}/"
                    if "/t/" not in app_url
                    else app_url,
                    params=values,
                    param_specs=specs,
                    llm_factory=factory,
                    policy=policy,
                    capability_id=capability_id,
                    app_id="meridian-core",
                    tenant=tenant,
                    runs_dir=self.runs_dir,
                    bridge=job.bridge,
                    trace=False,
                    on_start=on_ctx,
                    should_cancel=job.cancel.is_set,
                )
                saved = None
                if res.capability:
                    saved = str(Catalog(self.catalog_dir).save(res.capability))
                job.result = {
                    "status": res.status,
                    "summary": res.summary,
                    "actions": res.steps,
                    "capability_path": saved,
                    "capability_id": res.capability.id if res.capability else None,
                }
                job.status = "finished"
            except Exception as exc:  # surfaced to the UI
                job.status, job.error = "error", f"{type(exc).__name__}: {exc}"

        self._launch(job, run)
        return job

    def start_replay(
        self,
        capability_id: str,
        params: dict[str, Any],
        tenant: str | None = None,
        attended: bool = True,
        allow_draft: bool = False,
        faults: list[str] | None = None,
    ) -> Job:
        from glovebox.catalog import Catalog

        cap = Catalog(self.catalog_dir).load(capability_id)
        job = Job(
            id=f"job_{uuid.uuid4().hex[:8]}",
            kind="replay",
            title=cap.title,
            params=params,
            bridge=OperatorBridge(),
        )

        def run() -> None:
            from glovebox.runner import run_replay

            try:
                job.status = "running"
                policy = Policy.load(self.policy_path)
                values = {
                    **{
                        k: v
                        for k, v in self._creds().items()
                        if any(p.name == k for p in cap.inputs)
                    },
                    **params,
                }
                if faults:
                    import httpx

                    for f in faults:
                        httpx.post(f"{cap.app.origin}/__sim/faults/{f}", timeout=5)

                def on_ctx(run_id: str, run_dir: Path) -> None:
                    job.run_id, job.run_dir = run_id, run_dir

                res = run_replay(
                    cap,
                    values,
                    policy,
                    runs_dir=self.runs_dir,
                    tenant=tenant,
                    bridge=job.bridge,
                    attended=attended,
                    allow_draft=allow_draft,
                    trace=False,
                    on_start=on_ctx,
                    should_cancel=job.cancel.is_set,
                )
                Catalog(self.catalog_dir).record_replay(cap.id, res.answered)
                job.result = res.model_dump(mode="json")
                job.status = "finished"
            except Exception as exc:
                job.status, job.error = "error", f"{type(exc).__name__}: {exc}"

        self._launch(job, run)
        return job

    def _launch(self, job: Job, target: Any) -> None:
        with self._lock:
            self.jobs[job.id] = job
        job.thread = threading.Thread(target=target, daemon=True, name=job.id)
        job.thread.start()

    def cancel(self, job_id: str) -> Job:
        """Ask a running job to stop at its next step boundary.

        Cooperative by necessity: a daemon thread cannot be killed from outside, and tearing a
        browser down mid-action would leave evidence describing a step that never finished. The
        run stops between steps and reports `failed / cancelled`, which is neither an answer nor
        the capability breaking, so a caller can retry it verbatim.
        """
        job = self.jobs[job_id]
        if job.status in {"queued", "running"}:
            job.cancel.set()
            job.bridge.request_abort()
        return job

    # ------------------------------------------------------------------ queries
    def get(self, job_id: str) -> Job:
        return self.jobs[job_id]

    def all(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def for_run(self, run_id: str) -> Job | None:
        return next((j for j in self.jobs.values() if j.run_id == run_id), None)

    # ------------------------------------------------------------------ run files
    def runs(self) -> list[dict[str, Any]]:
        out = []
        for d in sorted(self.runs_dir.glob("*-*"), key=lambda p: p.stat().st_mtime, reverse=True):
            ev = d / "events.jsonl"
            if not ev.exists():
                continue
            out.append(self.run_summary(d.name))
        return out

    def run_summary(self, run_id: str) -> dict[str, Any]:
        d = self.runs_dir / run_id
        events = list(self.events(run_id))
        first = events[0] if events else {}
        last = events[-1] if events else {}
        result = None
        if (d / "result.json").exists():
            result = json.loads((d / "result.json").read_text())
        status = "running"
        if last.get("kind") == "run.finished":
            status = last.get("data", {}).get("status") or "finished"
        kind = "discovery" if run_id.startswith("discovery") else "replay"
        job = self.for_run(run_id)
        return {
            "run_id": run_id,
            "kind": kind,
            "status": status,
            "started_at": first.get("ts"),
            "finished_at": last.get("ts") if status != "running" else None,
            "title": first.get("message", ""),
            "events": len(events),
            "screenshots": len(list((d / "screenshots").glob("*.png")))
            if (d / "screenshots").exists()
            else 0,
            "result": result,
            "capability_id": (first.get("data") or {}).get("capability"),
            # The version matters as much as the id: reliability is a property of the
            # artifact in the catalog now, not of every version it has ever had.
            "capability_version": (first.get("data") or {}).get("version"),
            "job_id": job.id if job else None,
            "owner": ("human" if job and job.bridge.current else "automation"),
        }

    def events(self, run_id: str, offset: int = 0) -> Iterator[dict[str, Any]]:
        p = self.runs_dir / run_id / "events.jsonl"
        if not p.exists():
            return
        with p.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def stream(self, run_id: str) -> Iterator[str]:
        """Server-sent events: replay history, then follow the file until run.finished."""
        offset = 0
        idle = 0.0
        while True:
            got = False
            for ev in self.events(run_id, offset):
                offset += 1
                got = True
                yield f"data: {json.dumps(ev)}\n\n"
                if ev.get("kind") == "run.finished":
                    yield "event: end\ndata: {}\n\n"
                    return
            if not got:
                time.sleep(0.4)
                idle += 0.4
                if idle > 900:
                    return
                yield ": keepalive\n\n"
            else:
                idle = 0.0

    def artifact(self, run_id: str, name: str) -> Path | None:
        p = (self.runs_dir / run_id / name).resolve()
        if not str(p).startswith(str(self.runs_dir.resolve())) or not p.exists():
            return None
        return p

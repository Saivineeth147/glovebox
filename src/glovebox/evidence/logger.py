"""Run directory layout and the structured event log.

runs/<run_id>/
  events.jsonl        one redacted Event per line — the primary debugging record
  screenshots/        step-N-<label>.png
  snapshots/          <label>.html per frame on failure / escalation
  trace.zip           Playwright trace (when enabled)
  result.json         ReplayResult (replay runs)
  transcript.json     redacted model transcript (discovery runs)
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from glovebox.schema.events import Event, EventKind

from .redaction import Redactor


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"


@dataclass
class RunDir:
    root: Path

    @classmethod
    def create(cls, base: str | Path, run_id: str) -> RunDir:
        root = Path(base) / run_id
        for sub in ("screenshots", "snapshots"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        return cls(root)

    @property
    def events(self) -> Path:
        return self.root / "events.jsonl"

    def screenshot_path(self, label: str) -> Path:
        return self.root / "screenshots" / f"{int(time.time() * 1000)}-{_safe(label)}.png"

    def snapshot_path(self, label: str) -> Path:
        return self.root / "snapshots" / f"{int(time.time() * 1000)}-{_safe(label)}.html"

    def write_json(self, name: str, data: Any, redactor: Redactor | None = None) -> Path:
        p = self.root / name
        payload = redactor.obj(data) if redactor else data
        p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return p


class EvidenceLogger:
    """Append-only, redacted JSONL event sink plus optional console echo."""

    def __init__(self, run_id: str, run_dir: RunDir, redactor: Redactor, echo: bool = False) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.redactor = redactor
        self.echo = echo
        self._count = 0

    def emit(
        self, kind: EventKind, message: str, step_id: str | None = None, **data: Any
    ) -> Event:
        ev = Event(
            run_id=self.run_id,
            kind=kind,
            step_id=step_id,
            message=self.redactor.text(message),
            data=self.redactor.obj(data),
        )
        with self.run_dir.events.open("a", encoding="utf-8") as f:
            f.write(ev.model_dump_json() + "\n")
        self._count += 1
        if self.echo:
            step = f"[{step_id}] " if step_id else ""
            print(f"{ev.ts.strftime('%H:%M:%S')} {ev.kind:<26} {step}{ev.message}")
        return ev

    @property
    def count(self) -> int:
        return self._count


def _safe(label: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:60]

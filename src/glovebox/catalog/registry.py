"""The capability catalog: where approved artifacts live and how an AI agent discovers them.

`tool_definitions()` exposes every approved capability as a function-calling tool whose input
schema is derived from the artifact's typed parameters — the agent-facing product can hand
these straight to the model and route `tool_use` calls to `glovebox replay`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from glovebox.schema.capability import Capability, ParamType, ReviewState, ReviewStatus


class UnverifiedOutcomeError(Exception):
    """Approval was refused because a terminal outcome's detector was never observed.

    Such a detector never fires, so replay reports a hard failure where the catalog promised a
    business outcome and a calling agent branches on something it will never see.
    """

    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        super().__init__(
            f"unverified terminal outcome(s) {', '.join(codes)}: their detector text was never "
            "observed during discovery, so replay would report a hard failure instead"
        )


class Catalog:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, cap_id: str) -> Path:
        return self.dir / f"{cap_id}.json"

    def save(self, cap: Capability, *, bump: bool = True) -> Path:
        """Persist an artifact. A re-recording of an existing id gets the next patch version and
        a fresh draft review state, so approval never silently carries over to new steps."""
        p = self.path(cap.id)
        if bump and p.exists():
            existing = self.load(cap.id)
            if existing.provenance.discovery_run_id != cap.provenance.discovery_run_id:
                major, minor, patch = (int(x) for x in existing.version.split("."))
                cap = cap.model_copy(
                    update={"version": f"{major}.{minor}.{patch + 1}", "review": ReviewState()}
                )
        p.write_text(cap.model_dump_json(indent=2), encoding="utf-8")
        return p

    def load(self, ref: str) -> Capability:
        p = Path(ref) if ref.endswith(".json") else self.path(ref)
        if not p.exists():
            raise FileNotFoundError(f"no capability at {p}")
        return Capability.model_validate_json(p.read_text(encoding="utf-8"))

    def all(self) -> list[Capability]:
        """Every artifact that loads.

        One unreadable file must not take the catalog down with it: this backs both the Studio
        listing and `glovebox catalog list`, and a single artifact that fails validation — after
        a schema rule tightens, say — would otherwise blank the entire page. What failed is
        available from `problems()` so it is reported rather than hidden.
        """
        return [cap for cap, _ in self._loaded() if cap is not None]

    def problems(self) -> list[tuple[str, str]]:
        """Artifacts that did not load, as (name, reason)."""
        return [(name, reason) for cap, (name, reason) in self._loaded() if cap is None]

    def _loaded(self) -> list[tuple[Capability | None, tuple[str, str]]]:
        out: list[tuple[Capability | None, tuple[str, str]]] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                out.append((self.load(str(path)), (path.stem, "")))
            # Any malformed artifact: reported through problems(), never raised from here.
            except Exception as exc:
                out.append((None, (path.stem, str(exc).split("\n")[0])))
        return out

    def approve(
        self,
        cap_id: str,
        reviewer: str,
        notes: str | None = None,
        accept_unverified: bool = False,
    ) -> Capability:
        """Mark a capability fit for unattended replay.

        The unverified-outcome refusal lives here rather than in a command, because approval
        is reachable from the CLI and from Studio and a guard on one of them is not a guard.
        """
        cap = self.load(cap_id)
        unverified = [o.code for o in cap.outcomes if o.terminal and not o.verified]
        if unverified and not accept_unverified:
            raise UnverifiedOutcomeError(unverified)
        cap.review.status = ReviewStatus.APPROVED
        cap.review.reviewed_by = reviewer
        cap.review.reviewed_at = datetime.now(UTC)
        cap.review.notes = notes
        self.save(cap, bump=False)
        return cap

    def record_replay(self, cap_id: str, success: bool) -> Capability:
        cap = self.load(cap_id)
        cap.review.replays += 1
        cap.review.replay_successes += int(success)
        self.save(cap, bump=False)
        return cap

    def tool_definitions(self, include_drafts: bool = False) -> list[dict[str, Any]]:
        out = []
        for cap in self.all():
            if cap.review.status != ReviewStatus.APPROVED and not include_drafts:
                continue
            props: dict[str, Any] = {}
            required = []
            for p in cap.inputs:
                schema: dict[str, Any] = {"type": _json_type(p.type), "description": p.description}
                if p.pattern:
                    schema["pattern"] = p.pattern
                if p.enum:
                    schema["enum"] = p.enum
                props[p.name] = schema
                if p.required and p.default is None:
                    required.append(p.name)
            returns = {o.name: f"{o.type}: {o.description}" for o in cap.outputs}
            outcomes = {o.code: o.description for o in cap.outcomes}
            out.append(
                {
                    "name": cap.id,
                    "description": (
                        f"{cap.description} Returns {json.dumps(returns)}. "
                        f"Possible business outcomes: {json.dumps(outcomes) or 'none'}. "
                        f"Risk: {cap.max_risk}. Version {cap.version} ({cap.review.status})."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                        "additionalProperties": False,
                    },
                }
            )
        return out


def _json_type(t: ParamType) -> str:
    return {
        ParamType.STRING: "string",
        ParamType.INTEGER: "integer",
        ParamType.NUMBER: "number",
        ParamType.BOOLEAN: "boolean",
        ParamType.ENUM: "string",
    }[t]

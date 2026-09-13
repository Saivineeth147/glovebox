"""Input validation and value templating for replay."""

from __future__ import annotations

import re
from typing import Any

from glovebox.schema.capability import Capability, ParamType

_TEMPLATE = re.compile(r"\{\{\s*(params|app)\.([a-z][a-z0-9_]*)\s*\}\}")


class InputError(ValueError):
    pass


def referenced_parameters(steps: list[Any]) -> set[str]:
    """Parameter names the given steps actually substitute."""
    return {
        match.group(2)
        for step in steps
        for match in _TEMPLATE.finditer(step.value or "")
        if match.group(1) == "params"
    }


def validate_inputs(
    cap: Capability, raw: dict[str, Any], needed: set[str] | None = None
) -> dict[str, Any]:
    """Coerce and validate caller-supplied parameters against the capability contract.

    `needed` narrows which parameters are required to those the steps about to run actually
    substitute. A caller resuming into a warm session runs no sign-in step, so demanding the
    credentials would be asking for secrets the run has no use for — the opposite of what
    reusing a session is for.
    """
    out: dict[str, Any] = {}
    known = {p.name for p in cap.inputs}
    if unknown := set(raw) - known:
        raise InputError(f"unknown parameters: {sorted(unknown)}; expected {sorted(known)}")
    for p in cap.inputs:
        if p.name not in raw or raw[p.name] is None:
            if p.required and p.default is None and (needed is None or p.name in needed):
                raise InputError(f"missing required parameter {p.name!r}")
            if p.default is not None:
                out[p.name] = p.default
            continue
        v = raw[p.name]
        try:
            if p.type == ParamType.INTEGER:
                v = int(v)
            elif p.type == ParamType.NUMBER:
                v = float(v)
            elif p.type == ParamType.BOOLEAN:
                v = v if isinstance(v, bool) else str(v).lower() in {"1", "true", "yes"}
            else:
                v = str(v)
        except (TypeError, ValueError) as exc:
            raise InputError(f"parameter {p.name!r} is not a valid {p.type}: {v!r}") from exc
        if p.pattern and not re.fullmatch(p.pattern, str(v)):
            raise InputError(f"parameter {p.name!r} does not match pattern {p.pattern!r}")
        if p.enum and str(v) not in p.enum:
            raise InputError(f"parameter {p.name!r} must be one of {p.enum}")
        out[p.name] = v
    return out


def render_template(value: str, params: dict[str, Any], app: dict[str, Any] | None = None) -> str:
    """Substitute `{{ params.x }}` from the caller's inputs and `{{ app.x }}` from the AppRef."""

    def sub(m: re.Match[str]) -> str:
        scope, name = m.group(1), m.group(2)
        source = params if scope == "params" else (app or {})
        if name not in source:
            raise InputError(f"template references missing {scope}.{name}")
        return str(source[name])

    return _TEMPLATE.sub(sub, value)


def coerce_output(value: str, type_: ParamType) -> Any:
    v = value.strip()
    if type_ in {ParamType.NUMBER, ParamType.INTEGER}:
        cleaned = re.sub(r"[^0-9.\-]", "", v)
        try:
            return int(cleaned) if type_ == ParamType.INTEGER else float(cleaned)
        except ValueError:
            return v
    if type_ == ParamType.BOOLEAN:
        return v.lower() in {"true", "yes", "1", "y"}
    return v

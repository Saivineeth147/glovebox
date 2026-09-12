"""Load the `.env` file the README tells operators to create.

Every key Glovebox reads (model provider, target-app credentials) comes from the
process environment. Without this module `cp .env.example .env` is a no-op and the
documented setup silently yields "no model key found".
"""

from __future__ import annotations

import os
from pathlib import Path

_EXPORT_PREFIX = "export "
_QUOTE_CHARACTERS = ("'", '"')


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTE_CHARACTERS:
        return value[1:-1]
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse `KEY=value` lines. Absent file is not an error — the key may be exported.

    Inline `#` is kept: an API key may legitimately contain one, and truncating a
    secret at a hash produces a confusing 401 rather than a clear parse error.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith(_EXPORT_PREFIX):
            line = line[len(_EXPORT_PREFIX) :]
        name, _, value = line.partition("=")
        values[name.strip()] = _strip_quotes(value.strip())
    return values


def load_env_file(path: Path) -> list[str]:
    """Apply `path` to `os.environ` and return the names it set.

    An already-exported variable wins, so a CI secret or an operator's shell is never
    shadowed by a stale checked-out file. Names only in the return value: the caller
    logs them, and a value here would be a secret in a log line.
    """
    applied: list[str] = []
    for name, value in parse_env_file(path).items():
        if name in os.environ or not value:
            continue
        os.environ[name] = value
        applied.append(name)
    return applied

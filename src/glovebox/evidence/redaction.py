"""Redaction applied to everything that leaves memory: log lines, artifacts, transcripts.

Two layers:
1. **Registered secrets** — exact values known at run time (credentials, sensitive params).
   These are replaced wherever they appear, in any string, before anything is written.
2. **Pattern redaction** — regexes for things that must never be persisted even if we did not
   know about them in advance (API keys, bearer tokens, card PANs, US SSNs, password fields).

Replacement tokens keep the *kind* of thing visible (`[REDACTED:ssn]`) so evidence stays
debuggable without leaking the value. The hash of a registered secret is stable within a
run so a reviewer can tell "same member id used in steps 2 and 5" without seeing it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

_BUILTIN: list[tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}")),
    ("card_pan", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # The negative lookahead stops a second pass from re-redacting an already-redacted value:
    # `\S+` halts at the space inside "<hidden: sensitive>", which left the tail of the
    # placeholder dangling in committed evidence.
    (
        "password_kv",
        re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*(?!\[REDACTED|<hidden)\S+"),
    ),
    ("cookie", re.compile(r"(?i)(MCSESSION|sessionid|jsessionid)=[A-Za-z0-9]+")),
]


class Redactor:
    def __init__(self, extra_patterns: list[str] | None = None) -> None:
        self._secrets: dict[str, str] = {}  # value -> label
        self._patterns = list(_BUILTIN)
        for i, p in enumerate(extra_patterns or []):
            self._patterns.append((f"policy{i}", re.compile(p)))

    def register_secret(self, value: str | None, label: str) -> None:
        if value and len(value) >= 3:
            self._secrets[value] = label

    @staticmethod
    def fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:10]

    def text(self, s: str) -> str:
        for value, label in sorted(self._secrets.items(), key=lambda kv: -len(kv[0])):
            if value in s:
                s = s.replace(value, f"[REDACTED:{label}#{self.fingerprint(value)}]")
        for label, pat in self._patterns:
            if label == "password_kv":
                s = pat.sub(lambda m: f"{m.group(1)}=[REDACTED:password]", s)
            elif label == "cookie":
                s = pat.sub(lambda m: f"{m.group(1)}=[REDACTED:cookie]", s)
            else:
                s = pat.sub(f"[REDACTED:{label}]", s)
        return s

    def obj(self, value: Any) -> Any:
        """Recursively redact any JSON-like structure."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(k)): self.obj(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.obj(v) for v in value]
        return value

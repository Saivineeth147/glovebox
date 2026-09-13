"""Bound how fast an identity can be guessed at.

Gating the API raised the bar from nothing to one POST; leaving sign-in unbounded lowers it
again for anyone who knows an operator's email. The counter is in memory because Studio is one
process per institution — the same reason the job manager keeps its jobs there — and a limiter
that survived restarts would need a story about clearing it that nobody has asked for yet.
"""

from __future__ import annotations

import time
from collections.abc import Callable

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_WINDOW_SECONDS = 300


class TooManyAttempts(Exception):
    """Raised when an identity has failed too often inside the window."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"too many sign-in attempts; try again in {retry_after_seconds} seconds")


class AttemptLimiter:
    """Counts recent failures per identity and refuses once they are too many."""

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._now = now
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = self._now() - self._window
        recent = [at for at in self._failures.get(key, []) if at > cutoff]
        self._failures[key] = recent
        return recent

    def check(self, key: str) -> None:
        """Raise if `key` has failed too often lately. Called before the password is checked."""
        if len(self._recent(key)) >= self._max:
            raise TooManyAttempts(self._window)

    def record_failure(self, key: str) -> None:
        self._failures.setdefault(key, []).append(self._now())

    def clear(self, key: str) -> None:
        """Forget a identity's failures, which a successful sign-in earns."""
        self._failures.pop(key, None)

"""Unbounded password guessing against a known admin email is the gap auth left open."""

from __future__ import annotations

import pytest

from glovebox.studio.throttle import AttemptLimiter, TooManyAttempts


def test_should_allow_attempts_below_the_limit() -> None:
    limiter = AttemptLimiter(max_attempts=3, window_seconds=60)
    for _ in range(2):
        limiter.check("a@example.com")
        limiter.record_failure("a@example.com")
    limiter.check("a@example.com")


def test_should_refuse_once_the_limit_is_reached() -> None:
    limiter = AttemptLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        limiter.record_failure("a@example.com")
    with pytest.raises(TooManyAttempts):
        limiter.check("a@example.com")


def test_should_track_each_identity_separately() -> None:
    """One account under attack must not lock everyone else out."""
    limiter = AttemptLimiter(max_attempts=2, window_seconds=60)
    limiter.record_failure("a@example.com")
    limiter.record_failure("a@example.com")
    limiter.check("b@example.com")


def test_should_forget_attempts_once_the_window_has_passed() -> None:
    # two failures at t=0, then the check happens well past the window
    clock = iter([0.0, 0.0, 500.0])
    limiter = AttemptLimiter(max_attempts=2, window_seconds=60, now=lambda: next(clock))
    limiter.record_failure("a@example.com")
    limiter.record_failure("a@example.com")
    limiter.check("a@example.com")


def test_should_clear_the_count_after_a_successful_sign_in() -> None:
    limiter = AttemptLimiter(max_attempts=2, window_seconds=60)
    limiter.record_failure("a@example.com")
    limiter.clear("a@example.com")
    limiter.record_failure("a@example.com")
    limiter.check("a@example.com")


def test_should_say_how_long_to_wait() -> None:
    limiter = AttemptLimiter(max_attempts=1, window_seconds=300, now=lambda: 0.0)
    limiter.record_failure("a@example.com")
    with pytest.raises(TooManyAttempts, match="300"):
        limiter.check("a@example.com")

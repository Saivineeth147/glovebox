"""Fictional member data and the process-local fault injector."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field


@dataclass
class Member:
    member_id: str
    first_name: str
    last_name: str
    savings_balance: float
    checking_balance: float
    status: str = "Active"
    sub_accounts: list[dict[str, str]] = field(default_factory=list)


MEMBERS: dict[str, Member] = {
    "100234": Member("100234", "Jane", "Doe", 1250.75, 402.10),
    "100235": Member("100235", "Marcus", "Ng", 18_930.00, 1_020.55),
    "100236": Member("100236", "Priya", "Raman", 0.00, 55.00, status="Dormant"),
    # 100999 is reserved: lookups succeed but the teller role may not open sub-accounts for it.
    "100999": Member("100999", "Restricted", "Account", 5.00, 0.00, status="Legal hold"),
}

PRODUCTS = ["Holiday Club", "Vacation Savings", "Money Market", "Youth Saver"]

_ref_counter = itertools.count(start=48_112)
_lock = threading.Lock()


def next_reference() -> str:
    with _lock:
        return f"SA-{next(_ref_counter)}"


class FaultInjector:
    """Global, process-local fault switchboard used by tests and the evidence generator.

    A fault is armed with `arm(name, remaining=1)` and consumed by the next matching request.
    This mirrors how runtime faults show up in production: not on every request, unpredictably.
    """

    KNOWN = {
        "slow",  # main content takes several seconds to render
        "session_expired",  # next request bounces to the login page with a message
        "permission_denied",  # the action is refused for the current role
        "app_error",  # HTTP 500 with a generic application error page
        "interstitial",  # a "System notice" modal covers the page until dismissed
        "validation",  # the form rejects the submission with a field error
    }

    def __init__(self) -> None:
        self._armed: dict[str, int] = {}
        self._lock = threading.Lock()

    def arm(self, name: str, remaining: int = 1) -> None:
        if name not in self.KNOWN:
            raise ValueError(f"unknown fault {name!r}; known: {sorted(self.KNOWN)}")
        with self._lock:
            self._armed[name] = remaining

    def clear(self) -> None:
        with self._lock:
            self._armed.clear()

    def consume(self, name: str) -> bool:
        with self._lock:
            left = self._armed.get(name, 0)
            if left <= 0:
                return False
            if left == 1:
                del self._armed[name]
            else:
                self._armed[name] = left - 1
            return True

    def armed(self) -> dict[str, int]:
        with self._lock:
            return dict(self._armed)


FAULTS = FaultInjector()

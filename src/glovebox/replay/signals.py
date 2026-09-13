"""The control-flow signals a replay raises.

They live apart from the engine because both halves of it — the step loop and the code that
decides what a failure means — raise them, and a module that only holds exceptions cannot
create an import cycle between the two.
"""

from __future__ import annotations

from glovebox.schema.capability import Recovery
from glovebox.schema.results import ReplayResult


class _ExtractionMismatch(Exception):
    """The text under a resolved target did not have the shape the step recorded.

    Raised rather than stopping on the spot so the caller can record which strategy resolved
    the target — the drift evaluation reads exactly that — and so an attended run offers the
    operator the same takeover every other checkpoint failure does.
    """

    def __init__(self, output: str, expected: str, observed: str) -> None:
        self.output, self.expected, self.observed = output, expected, observed
        super().__init__(
            f"{output} did not match the shape recorded for it; the screen is not the one "
            "this step was recorded against"
        )


class _Stop(Exception):
    def __init__(self, result: ReplayResult) -> None:
        self.result = result


class _Recover(Exception):
    def __init__(self, recovery: Recovery) -> None:
        self.recovery = recovery


class _RetryAfterHuman(Exception):
    pass


class _RestartAfterHuman(Exception):
    pass

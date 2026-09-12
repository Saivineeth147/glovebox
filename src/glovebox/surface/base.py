from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from glovebox.schema.capability import Condition, Target


class SurfaceError(Exception):
    pass


@dataclass
class Element:
    """A perceivable control or piece of content, described the way an operator would."""

    ref: str  # ephemeral id valid for one observation (e.g. "e12")
    frame: list[str]
    role: str  # button | link | textbox | combobox | checkbox | radio | cell | heading | text | dialog
    name: str  # accessible name (label/text/aria/value)
    text: str  # own visible text, trimmed
    label: str | None  # associated or adjacent label text (legacy table forms)
    name_attr: str | None  # form control `name`
    tag: str
    css: str  # structural path usable as a fallback locator
    bbox: tuple[float, float, float, float]  # x, y, w, h in viewport px
    nbox: tuple[float, float]  # normalized centre (0..1, 0..1)
    interactive: bool
    value: str | None = None
    href: str | None = None
    options: list[str] = field(default_factory=list)
    table: str | None = None  # css of the enclosing table (cells only)
    row: int = -1
    col: int = -1

    def summary(self) -> str:
        bits = [f"[{self.ref}] {self.role}"]
        if self.name:
            bits.append(f'"{self.name}"')
        if self.label and self.label != self.name:
            bits.append(f"label={self.label!r}")
        if self.name_attr:
            bits.append(f"name={self.name_attr}")
        if self.value:
            bits.append(f"value={self.value!r}")
        if self.options:
            bits.append(f"options={self.options}")
        if self.frame:
            bits.append(f"frame={'/'.join(self.frame)}")
        return " ".join(bits)


@dataclass
class DialogInfo:
    kind: str
    message: str
    handled: Literal["accept", "dismiss"] | None


@dataclass
class Observation:
    seq: int
    url: str
    title: str
    frames: list[list[str]]
    elements: list[Element]
    text: str  # visible text, per frame, truncated
    dialog: DialogInfo | None
    last_status: int | None
    screenshot: Path | None

    def element(self, ref: str) -> Element:
        for e in self.elements:
            if e.ref == ref:
                return e
        raise SurfaceError(f"unknown element ref {ref!r} (refs are only valid for the latest observation)")

    def render_for_model(self, max_elements: int = 120, max_text: int = 3000) -> str:
        lines = [f"URL: {self.url}", f"TITLE: {self.title}"]
        if self.last_status:
            lines.append(f"LAST HTTP STATUS: {self.last_status}")
        if self.dialog:
            lines.append(f"NATIVE DIALOG ({self.dialog.kind}): {self.dialog.message!r} -> {self.dialog.handled}")
        lines.append(f"FRAMES: {[ '/'.join(f) or '(top)' for f in self.frames ]}")
        lines.append("INTERACTIVE ELEMENTS:")
        shown = [e for e in self.elements if e.interactive][:max_elements]
        lines += [f"  {e.summary()}" for e in shown]
        if not shown:
            lines.append("  (none)")
        lines.append("VISIBLE TEXT:")
        lines.append(self.text[:max_text])
        return "\n".join(lines)


@dataclass
class Resolved:
    element: Element
    strategy_kind: str
    strategy_index: int


class Surface(Protocol):
    """What the agent loop and replay engine require from any surface implementation."""

    def observe(self, *, screenshot: bool = False, label: str = "obs") -> Observation: ...
    def navigate(self, url: str) -> None: ...
    def click(self, element: Element) -> None: ...
    def fill(self, element: Element, value: str) -> None: ...
    def select(self, element: Element, value: str) -> None: ...
    def press(self, key: str, element: Element | None = None) -> None: ...
    def arm_dialog(self, response: Literal["accept", "dismiss"]) -> None: ...
    def wait_settled(self, load_state: str, settle_ms: int, timeout_ms: int) -> None: ...
    def resolve(self, target: Target) -> Resolved: ...
    def check(self, condition: Condition) -> tuple[bool, str]: ...
    def describe_target(self, element: Element) -> Target: ...
    def capture(self, label: str) -> dict[str, str]: ...
    def current_url(self) -> str: ...
    def close(self) -> None: ...
    def raw(self) -> Any: ...

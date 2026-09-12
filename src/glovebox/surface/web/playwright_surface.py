"""Playwright-backed web surface.

Everything Playwright-specific lives here. The agent loop and replay engine never import
Playwright. All calls happen on the thread that owns the sync Playwright context — the
operator console therefore hands commands to this thread via a queue rather than calling
into the page directly (see glovebox.control).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Literal

from playwright.sync_api import Browser, BrowserContext, Dialog, Frame, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from glovebox.evidence.logger import RunDir
from glovebox.schema.capability import Condition, ConditionKind, Target
from glovebox.surface.base import DialogInfo, Element, Observation, Resolved, SurfaceError

from . import locators

_WALKER = (Path(__file__).parent / "walker.js").read_text(encoding="utf-8")


class PlaywrightSurface:
    def __init__(
        self,
        run_dir: RunDir,
        *,
        headless: bool = True,
        viewport: tuple[int, int] = (1100, 800),
        trace: bool = True,
        slow_mo: int = 0,
    ) -> None:
        self.run_dir = run_dir
        self._pw = sync_playwright().start()
        self._browser: Browser = self._pw.chromium.launch(headless=headless, slow_mo=slow_mo)
        self._ctx: BrowserContext = self._browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        self._viewport = viewport
        self._trace = trace
        if trace:
            self._ctx.tracing.start(screenshots=True, snapshots=True)
        self.page: Page = self._ctx.new_page()
        self._seq = 0
        self._last_obs: Observation | None = None
        self._armed_dialog: Literal["accept", "dismiss"] | None = None
        self._last_dialog: DialogInfo | None = None
        self._last_status: int | None = None
        self.page.on("dialog", self._on_dialog)
        self.page.on("response", self._on_response)

    # ------------------------------------------------------------------ events
    def _on_dialog(self, dialog: Dialog) -> None:
        response = self._armed_dialog or "dismiss"
        self._last_dialog = DialogInfo(kind=dialog.type, message=dialog.message, handled=response)
        self._armed_dialog = None
        if response == "accept":
            dialog.accept()
        else:
            dialog.dismiss()

    def _on_response(self, resp: Any) -> None:
        try:
            if resp.request.resource_type == "document":
                self._last_status = resp.status
        except Exception:  # noqa: S110 — response objects can be torn down mid-navigation
            pass

    # ------------------------------------------------------------------ frames
    def _frames(self) -> list[tuple[list[str], Frame]]:
        out: list[tuple[list[str], Frame]] = []

        def walk(fr: Frame, path: list[str]) -> None:
            if fr.is_detached():
                return
            out.append((path, fr))
            for child in fr.child_frames:
                walk(child, [*path, child.name or f"#{len(path)}"])

        walk(self.page.main_frame, [])
        return out

    def _frame_offset(self, fr: Frame) -> tuple[float, float]:
        """Offset of a frame's viewport within the page, so element boxes can be drawn on a screenshot."""
        if fr == self.page.main_frame:
            return 0.0, 0.0
        try:
            handle = fr.frame_element()
            box = handle.bounding_box()
            parent = fr.parent_frame
            px, py = self._frame_offset(parent) if parent is not None else (0.0, 0.0)
            return (box["x"] + px, box["y"] + py) if box else (px, py)
        except PlaywrightError:
            return 0.0, 0.0

    def _frame(self, path: list[str]) -> Frame:
        for p, fr in self._frames():
            if p == path:
                return fr
        raise SurfaceError(f"frame {'/'.join(path) or '(top)'} not found")

    # ------------------------------------------------------------------ observe
    def observe(self, *, screenshot: bool = False, label: str = "obs") -> Observation:
        self._seq += 1
        elements: list[Element] = []
        texts: list[str] = []
        frames: list[list[str]] = []
        title = self.page.title()
        for path, fr in self._frames():
            frames.append(path)
            ox, oy = self._frame_offset(fr)
            try:
                data = fr.evaluate(_WALKER)
            except Exception as exc:
                texts.append(f"[{'/'.join(path) or 'top'}] (unavailable: {type(exc).__name__})")
                continue
            for raw in data["elements"]:
                elements.append(
                    Element(
                        ref=f"e{len(elements) + 1}",
                        frame=path,
                        role=raw["role"],
                        name=raw["name"],
                        text=raw["text"],
                        label=raw["label"],
                        name_attr=raw["name_attr"],
                        tag=raw["tag"],
                        css=raw["css"],
                        bbox=(raw["bbox"][0], raw["bbox"][1], raw["bbox"][2], raw["bbox"][3]),
                        nbox=(raw["nbox"][0], raw["nbox"][1]),
                        page_box=(
                            raw["bbox"][0] + ox,
                            raw["bbox"][1] + oy,
                            raw["bbox"][2],
                            raw["bbox"][3],
                        ),
                        interactive=bool(raw["interactive"]),
                        value=raw["value"],
                        href=raw["href"],
                        options=list(raw["options"]),
                        table=raw.get("table"),
                        row=raw.get("row", -1),
                        col=raw.get("col", -1),
                    )
                )
            if data["text"]:
                texts.append(f"[{'/'.join(path) or 'top'}]\n{data['text']}")
        shot = None
        if screenshot:
            shot = self.run_dir.screenshot_path(label)
            self.page.screenshot(path=str(shot), full_page=False)
        obs = Observation(
            seq=self._seq,
            url=self.page.url,
            title=title,
            frames=frames,
            elements=elements,
            text="\n\n".join(texts),
            dialog=self._last_dialog,
            last_status=self._last_status,
            screenshot=shot,
            viewport=self._viewport,
        )
        self._last_dialog = None
        self._last_obs = obs
        return obs

    # ------------------------------------------------------------------ act
    def _locator(self, el: Element) -> Any:
        for attempt in range(2):
            loc = self._frame(el.frame).locator(el.css)
            try:
                n = loc.count()
            except PlaywrightError as exc:
                if "detached" in str(exc) and attempt == 0:
                    time.sleep(0.2)  # the frame was replaced by a navigation; re-resolve once
                    continue
                raise
            if n != 1:
                raise SurfaceError(f"element {el.ref} ({el.css}) no longer resolves uniquely")
            return loc
        raise SurfaceError(f"frame {'/'.join(el.frame)} keeps detaching")

    def navigate(self, url: str) -> None:
        with _Wrap("navigate", url):
            self.page.goto(url, wait_until="load")

    def click(self, element: Element) -> None:
        with _Wrap("click", element.ref):
            self._locator(element).click(timeout=5000)

    def fill(self, element: Element, value: str) -> None:
        with _Wrap("fill", element.ref):
            self._locator(element).fill(value, timeout=5000)

    def select(self, element: Element, value: str) -> None:
        with _Wrap("select", element.ref):
            loc = self._locator(element)
            try:
                loc.select_option(label=value, timeout=5000)
            except PlaywrightError:  # fall back to matching by value
                loc.select_option(value=value, timeout=5000)

    def press(self, key: str, element: Element | None = None) -> None:
        with _Wrap("press", key):
            if element is not None:
                self._locator(element).press(key, timeout=5000)
            else:
                self.page.keyboard.press(key)

    def arm_dialog(self, response: Literal["accept", "dismiss"]) -> None:
        self._armed_dialog = response

    def wait_settled(self, load_state: str, settle_ms: int, timeout_ms: int) -> None:
        if load_state != "none":
            try:
                self.page.wait_for_load_state(load_state, timeout=timeout_ms)  # type: ignore[arg-type]
                for fr in self.page.frames:
                    fr.wait_for_load_state("load", timeout=timeout_ms)
            except Exception as exc:
                raise SurfaceError(
                    f"page did not reach {load_state} within {timeout_ms}ms"
                ) from exc
        if settle_ms:
            time.sleep(settle_ms / 1000)

    # ------------------------------------------------------------------ targeting
    def resolve(self, target: Target) -> Resolved:
        obs = self.observe(label="resolve")
        return locators.resolve(target, obs.elements)

    def describe_target(self, element: Element) -> Target:
        obs = self._last_obs or self.observe()
        return locators.describe(element, obs.elements)

    # ------------------------------------------------------------------ conditions
    def check(self, condition: Condition) -> tuple[bool, str]:
        deadline = time.monotonic() + condition.timeout_ms / 1000
        last = ""
        while True:
            ok, last = self._check_once(condition)
            if ok or time.monotonic() >= deadline:
                return ok, last
            time.sleep(0.2)

    def _check_once(self, c: Condition) -> tuple[bool, str]:
        k = c.kind
        if k == ConditionKind.DIALOG_OPEN:
            d = self._last_dialog
            if d is None:
                return False, "no dialog"
            hit = c.value is None or _text_match(c.value, d.message, c.regex)
            return hit, f"dialog {d.message!r}"
        if k == ConditionKind.HTTP_STATUS:
            s = self._last_status
            return (s is not None and _text_match(c.value or "", str(s), True)), f"status {s}"
        if k == ConditionKind.URL_MATCHES:
            url = self._frame(c.frame).url if c.frame else self.page.url
            return _text_match(c.value or "", url, True), url
        if k == ConditionKind.TITLE_MATCHES:
            t = self.page.title()
            return _text_match(c.value or "", t, c.regex), t
        obs = self.observe(label="check")
        if k == ConditionKind.ELEMENT_VISIBLE:
            assert c.target is not None
            try:
                r = locators.resolve(c.target, obs.elements)
                return True, f"resolved via {r.strategy_kind}"
            except SurfaceError as exc:
                return False, str(exc)
        text = obs.text
        if c.frame:
            text = "\n".join(e.text for e in obs.elements if e.frame == c.frame) + "\n" + text
        present = _text_match(c.value or "", text, c.regex)
        if k == ConditionKind.TEXT_VISIBLE:
            return present, ("found" if present else f"text {c.value!r} not visible")
        return (not present), ("absent" if not present else f"text {c.value!r} is visible")

    # ------------------------------------------------------------------ evidence
    def capture(self, label: str) -> dict[str, str]:
        out: dict[str, str] = {}
        shot = self.run_dir.screenshot_path(label)
        try:
            self.page.screenshot(path=str(shot), full_page=True)
            out["screenshot"] = str(shot)
        except Exception as exc:
            out["screenshot_error"] = str(exc)
        for path, fr in self._frames():
            try:
                snap = self.run_dir.snapshot_path(f"{label}-{'_'.join(path) or 'top'}")
                snap.write_text(fr.content(), encoding="utf-8")
                out[f"snapshot:{'/'.join(path) or 'top'}"] = str(snap)
            except Exception:  # noqa: S112 — a frame can detach while we snapshot it
                continue
        return out

    def current_url(self) -> str:
        return self.page.url

    def raw(self) -> Page:
        return self.page

    def close(self) -> None:
        try:
            if self._trace:
                self._ctx.tracing.stop(path=str(self.run_dir.root / "trace.zip"))
        finally:
            self._ctx.close()
            self._browser.close()
            self._pw.stop()


class _Wrap:
    """Translate Playwright errors into SurfaceError with a one-line, operator-readable reason."""

    def __init__(self, op: str, what: str) -> None:
        self.op, self.what = op, what

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc is None or isinstance(exc, SurfaceError):
            return
        if isinstance(exc, PlaywrightError):
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            reason = first
            if "intercepts pointer events" in str(exc):
                reason = "another element covers the target (modal/interstitial?)"
            elif "Timeout" in type(exc).__name__ or "Timeout" in first:
                reason = f"timed out: {first[:120]}"
            raise SurfaceError(f"{self.op} {self.what} failed: {reason}") from exc


def _text_match(pattern: str, haystack: str, regex: bool) -> bool:
    if regex:
        return re.search(pattern, haystack, re.IGNORECASE | re.DOTALL) is not None
    return pattern.lower() in haystack.lower()

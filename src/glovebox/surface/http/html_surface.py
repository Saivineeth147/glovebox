"""A `Surface` that drives a server-rendered application over HTTP, with no browser.

Seam 1 says the artifact describes what an operator perceives rather than what Playwright
does. This is that claim tested rather than argued: the same reviewed capability replays
through a surface that has no DOM, no JavaScript and no layout engine, resolved by the same
`locators` module.

What it deliberately cannot do is as informative as what it can. There is no geometry here, so
a `bbox` strategy simply fails; there is no script engine, so a native dialog is refused rather
than faked. A legacy back-office screen needs neither, which is the point — and a capability
that depended on them would fail loudly here instead of silently elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import httpx

from glovebox.schema.capability import Condition, ConditionKind, Target
from glovebox.surface.base import (
    Element,
    Observation,
    Resolved,
    SurfaceError,
)
from glovebox.surface.http.page import Form, Page, parse_page
from glovebox.surface.web import locators

DEFAULT_TIMEOUT_SECONDS = 15.0


def _frame_of(element: Element) -> str | None:
    return element.frame[0] if element.frame else None


class HtmlSurface:
    """Operates the application the way a terminal-era client would: fetch, fill, submit."""

    def __init__(self, base_url: str, *, evidence_dir: Path | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base, follow_redirects=True, timeout=DEFAULT_TIMEOUT_SECONDS
        )
        self._evidence = evidence_dir
        self._url = self._base + "/"
        self._status: int | None = None
        self._pages: list[tuple[list[str], Page]] = []
        self._frame_urls: dict[str, str] = {}
        self._targets: dict[int, str] = {}
        self._elements: list[Element] = []
        self._pending: dict[str, str] = {}
        self._seq = 0

    # ------------------------------------------------------------------ navigation
    def navigate(self, url: str) -> None:
        self._fetch(url)

    def _fetch(
        self,
        url: str,
        method: str = "get",
        data: dict[str, str] | None = None,
        frame: str | None = None,
    ) -> None:
        """Fetch into `frame` when the action came from one, or reload the document otherwise.

        A form submitted inside a frame navigates that frame alone; the surrounding panes stay
        as they were. Replacing the whole document instead would lose the menu the moment an
        operator signed in — which is why a recorded target carries its frame path.
        """
        response = self._client.request(method, url, data=data)
        self._status = response.status_code
        self._pending = {}
        if frame and any(path and path[0] == frame for path, _page in self._pages):
            self._frame_urls[frame] = str(response.url)
            self._replace_frame(frame, response.text)
            return
        self._url = str(response.url)
        self._load_documents(response.text)

    def _replace_frame(self, frame: str, html: str) -> None:
        base = self._frame_urls.get(frame, self._url)
        self._pages = [
            (path, parse_page(html, path, base) if path and path[0] == frame else page)
            for path, page in self._pages
        ]
        self._renumber()

    def _load_documents(self, html: str) -> None:
        """Read the document, and each pane of it when the document is a frameset."""
        top = parse_page(html, [], self._url)
        if not top.frames:
            self._pages = [(["main"], top)]
            self._renumber()
            return
        pages: list[tuple[list[str], Page]] = []
        for frame in top.frames:
            response = self._client.get(frame.src)
            self._frame_urls[frame.name] = str(response.url)
            pages.append(([frame.name], parse_page(response.text, [frame.name], str(response.url))))
        self._pages = pages
        self._renumber()

    def _destination_frame(self, element: Element) -> str | None:
        """Where a control's navigation lands: the frame it names, else the one it sits in."""
        return self._targets.get(id(element)) or _frame_of(element)

    def _renumber(self) -> None:
        """Refs are ephemeral and unique across panes, exactly as the browser surface makes them."""
        self._elements = []
        self._targets = {}
        for _frame, page in self._pages:
            self._targets.update(page.targets)
            for element in page.elements:
                self._elements.append(element)
        for index, element in enumerate(self._elements, start=1):
            element.ref = f"e{index}"

    # ------------------------------------------------------------------ perception
    def observe(self, *, screenshot: bool = False, label: str = "obs") -> Observation:
        self._seq += 1
        return Observation(
            seq=self._seq,
            url=self._url,
            title=next((p.title for _f, p in self._pages if p.title), ""),
            frames=[frame for frame, _page in self._pages],
            elements=list(self._elements),
            text=self._text(),
            dialog=None,
            last_status=self._status,
            screenshot=None,  # there is nothing to photograph without a renderer
            viewport=(0, 0),
        )

    def _text(self) -> str:
        return " ".join(page.text for _frame, page in self._pages)

    def current_url(self) -> str:
        return self._url

    # ------------------------------------------------------------------ action
    def click(self, element: Element) -> None:
        if element.role == "link" and element.href:
            self._fetch(element.href, frame=self._destination_frame(element))
            return
        if element.role == "button":
            self._submit(element)
            return
        raise SurfaceError(f"cannot click {element.role} {element.name!r} without a browser")

    def _submit(self, button: Element) -> None:
        form = self._form_for(button)
        fields = {**form.fields, **self._pending}
        if button.name_attr:
            fields[button.name_attr] = button.name
        self._fetch(form.action, form.method, fields, frame=self._destination_frame(button))

    def _form_for(self, button: Element) -> Form:
        forms = [form for _frame, page in self._pages for form in page.forms]
        if not forms:
            raise SurfaceError(f"no form to submit for {button.name!r}")
        if len(forms) > 1:
            raise SurfaceError(
                f"{len(forms)} forms on this screen and no way to tell which {button.name!r} "
                "belongs to; this surface handles one form per screen"
            )
        return forms[0]

    def fill(self, element: Element, value: str) -> None:
        if not element.name_attr:
            raise SurfaceError(f"{element.name!r} has no form name to submit under")
        self._pending[element.name_attr] = value
        element.value = value

    def select(self, element: Element, value: str) -> None:
        raise SurfaceError("select is not implemented on the HTTP surface")

    def press(self, key: str, element: Element | None = None) -> None:
        raise SurfaceError("key presses need a browser; use the control that the key triggers")

    def arm_dialog(self, response: Literal["accept", "dismiss"]) -> None:
        raise SurfaceError("native dialogs need a script engine, which this surface has none of")

    def wait_settled(self, load_state: str, settle_ms: int, timeout_ms: int) -> None:
        """A response is the settled state: there is nothing rendering after it arrives."""

    # ------------------------------------------------------------------ resolution
    def resolve(self, target: Target) -> Resolved:
        return locators.resolve(target, self._elements)

    def describe_target(self, element: Element) -> Target:
        return locators.describe(element, self._elements)

    def check(self, condition: Condition) -> tuple[bool, str]:
        text = self._text()
        if condition.kind == ConditionKind.TEXT_VISIBLE:
            value = condition.value or ""
            return value.lower() in text.lower(), text[:400]
        if condition.kind == ConditionKind.URL_MATCHES:
            return (condition.value or "") in self._url, self._url
        if condition.kind == ConditionKind.ELEMENT_VISIBLE and condition.target:
            try:
                self.resolve(condition.target)
            except SurfaceError as exc:
                return False, str(exc)
            return True, condition.target.description
        return False, f"{condition.kind} is not checkable without a browser"

    # ------------------------------------------------------------------ evidence
    def capture(self, label: str) -> dict[str, str]:
        """Evidence here is the served markup: the only artefact this surface actually has."""
        if self._evidence is None:
            return {}
        directory = self._evidence / "snapshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{label}.html"
        path.write_text("\n".join(page.text for _frame, page in self._pages), encoding="utf-8")
        return {"snapshot": str(path)}

    def close(self) -> None:
        self._client.close()

    def raw(self) -> Any:
        return self._client

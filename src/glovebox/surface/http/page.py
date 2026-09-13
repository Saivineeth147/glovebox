"""Turn a server-rendered page into the same `Element` vocabulary the browser surface emits.

The point is the seam. `surface/web/locators.py` resolves a recorded target against a list of
`Element`s and knows nothing about Playwright, so if that vocabulary really is surface-agnostic
then a parser with no browser behind it can feed the same resolver and replay the same
artifact. Anything this cannot supply — geometry, above all — is left empty rather than
invented, which is how the portability of each locator strategy becomes visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

from glovebox.surface.base import Element

#: Geometry a page has only once a browser has laid it out. Left at the origin so a bbox
#: strategy simply fails to resolve here instead of resolving to something invented.
NO_GEOMETRY = (0.0, 0.0, 0.0, 0.0)

_TEXT_INPUTS = {"text", "password", "search", "email", "tel", "number", ""}
_BUTTON_INPUTS = {"submit", "button"}
_VOID_TAGS = {"input", "br", "img", "hr", "meta", "link", "frame"}
_CELL_TAGS = {"td", "th"}


@dataclass(frozen=True)
class Frame:
    """One pane of a frameset, which the surface fetches as its own document."""

    name: str
    src: str


@dataclass(frozen=True)
class Form:
    """A form and the fields that submit with it."""

    action: str
    method: str
    fields: dict[str, str]


@dataclass
class Page:
    elements: list[Element] = field(default_factory=list)
    #: Destination frame for a control that names one, keyed by element identity. A menu
    #: link in a frameset loads into `main`, not into the pane holding the link.
    targets: dict[int, str] = field(default_factory=dict)
    forms: list[Form] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    text: str = ""
    title: str = ""


class _PageParser(HTMLParser):
    """Walks the document once, building elements, forms and frame references."""

    def __init__(self, frame: list[str], base_url: str, start_ref: int) -> None:
        super().__init__(convert_charrefs=True)
        self.page = Page()
        self._frame = frame
        self._base = base_url
        self._ref = start_ref
        self._path: list[tuple[str, int]] = []
        self._sibling_counts: list[dict[str, int]] = [{}]
        self._text_parts: list[str] = []
        self._cell_text: list[str] = []
        self._in_title = False
        self._table_depth = 0
        self._row = -1
        self._col = -1
        self._row_labels: list[str] = []
        self._open_form: dict[str, str] | None = None
        self._form_fields: dict[str, str] = {}
        self._open_link: Element | None = None
        # Two links can share one cell, so a link's text needs its own buffer or the
        # second inherits the first.
        self._link_text: list[str] = []

    # ------------------------------------------------------------------ helpers
    def _next_ref(self) -> str:
        self._ref += 1
        return f"e{self._ref}"

    def _css(self, tag: str) -> str:
        parts = [f"{name}:nth-of-type({index})" for name, index in self._path]
        return " > ".join([*parts, tag])

    def _table_css(self) -> str | None:
        for index, (name, _count) in enumerate(self._path):
            if name == "table":
                return " > ".join(f"{n}:nth-of-type({c})" for n, c in self._path[: index + 1])
        return None

    def _add(self, **kwargs: object) -> Element:
        fields: dict[str, object] = {
            "ref": self._next_ref(),
            "frame": list(self._frame),
            "text": "",
            "label": None,
            "name_attr": None,
            "bbox": NO_GEOMETRY,
            "nbox": (0.0, 0.0),
            "page_box": NO_GEOMETRY,
            "interactive": True,
        }
        fields.update(kwargs)
        element = Element(**fields)  # type: ignore[arg-type]
        self.page.elements.append(element)
        return element

    def _label_for_field(self) -> str | None:
        return self._row_labels[-1] if self._row_labels else None

    # ------------------------------------------------------------------ tags
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k: (v or "") for k, v in attrs}
        counts = self._sibling_counts[-1]
        counts[tag] = counts.get(tag, 0) + 1
        index = counts[tag]

        if tag == "title":
            self._in_title = True
        elif tag == "frame":
            self.page.frames.append(Frame(attributes.get("name", ""), attributes.get("src", "")))
        elif tag == "form":
            self._open_form = attributes
            self._form_fields = {}
        elif tag == "table":
            self._table_depth += 1
            self._row = -1
        elif tag == "tr":
            self._row += 1
            self._col = -1
            self._row_labels = []
        elif tag in _CELL_TAGS:
            self._col += 1
            self._cell_text = []
        elif tag == "a":
            self._link_text = []
            self._open_link = self._add(
                role="link",
                name="",
                tag="a",
                css=self._css(tag),
                href=urljoin(self._base, attributes.get("href", "")),
                table=self._table_css(),
                row=self._row,
                col=self._col,
            )
            if attributes.get("target"):
                self.page.targets[id(self._open_link)] = attributes["target"]
        elif tag == "input":
            self._handle_input(attributes, tag)

        if tag not in _VOID_TAGS:
            self._path.append((tag, index))
            self._sibling_counts.append({})

    def _handle_input(self, attributes: dict[str, str], tag: str) -> None:
        kind = attributes.get("type", "text").lower()
        name_attr = attributes.get("name")
        value = attributes.get("value", "")
        if name_attr is not None and self._open_form is not None:
            self._form_fields[name_attr] = value
        common = {
            "tag": tag,
            "css": self._css(tag),
            "table": self._table_css(),
            "row": self._row,
            "col": self._col,
        }
        if kind in _BUTTON_INPUTS:
            self._add(role="button", name=value, name_attr=name_attr, **common)
        elif kind in _TEXT_INPUTS:
            element = self._add(role="textbox", name="", value=value, **common)
            element.name_attr = name_attr
            element.label = self._label_for_field()
            element.name = element.label or name_attr or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "form" and self._open_form is not None:
            self.page.forms.append(
                Form(
                    action=urljoin(self._base, self._open_form.get("action", "")),
                    method=self._open_form.get("method", "get").lower(),
                    fields=dict(self._form_fields),
                )
            )
            self._open_form = None
        elif tag == "table":
            self._table_depth = max(0, self._table_depth - 1)
        elif tag in _CELL_TAGS:
            self._close_cell()
        elif tag == "a" and self._open_link is not None:
            text = " ".join("".join(self._link_text).split())
            self._open_link.name = self._open_link.name or text
            self._open_link.text = text
            self._open_link = None

        if tag not in _VOID_TAGS and self._path and self._path[-1][0] == tag:
            self._path.pop()
            self._sibling_counts.pop()

    def _close_cell(self) -> None:
        text = " ".join("".join(self._cell_text).split())
        self._row_labels.append(text)
        self._add(
            role="cell",
            name=text,
            tag="td",
            css=self._css("td"),
            table=self._table_css(),
            row=self._row,
            col=self._col,
        ).text = text
        self.page.elements[-1].interactive = False
        self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.page.title += data.strip()
            return
        self._text_parts.append(data)
        self._cell_text.append(data)
        if self._open_link is not None:
            self._link_text.append(data)

    def result(self) -> Page:
        self.page.text = " ".join(" ".join(self._text_parts).split())
        return self.page


def parse_page(html: str, frame: list[str], base_url: str, start_ref: int = 0) -> Page:
    """Parse one document into elements, forms and frame references."""
    parser = _PageParser(frame, base_url, start_ref)
    parser.feed(html)
    parser.close()
    return parser.result()

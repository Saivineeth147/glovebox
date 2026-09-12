"""Turn a live Element into a multi-strategy `Target`, and resolve a `Target` back to exactly
one Element on a later observation.

Strategy order encodes a robustness argument (REPORT.md §3):
1. role_name   — what a screen reader (and a human) uses; survives restyling and DOM moves.
2. label       — legacy table forms have visible labels even when there is no <label>.
3. name_attr   — form `name` attributes are wired to the server and almost never change.
4. text        — link/button text; changes with copy edits, not with layout.
5. near_text   — spatial relation to an anchor; survives label renames when the anchor stays.
6. css         — structural path; survives nothing but is exact on an unchanged page.
7. bbox        — normalized position; the only strategy a pure screenshot surface has.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

from glovebox.schema.capability import Target, TargetStrategy
from glovebox.surface.base import Element, Resolved, SurfaceError


def describe(el: Element, all_elements: list[Element]) -> Target:
    strategies: list[TargetStrategy] = []
    same_frame = [e for e in all_elements if e.frame == el.frame]

    if el.role == "cell" and not el.interactive:
        # Data cells: the *value* is what we extract, so it must never be the locator.
        # Locate by table geometry instead: the row's label cell and the column's header.
        tc = _table_cell_strategy(el, same_frame)
        if tc is not None:
            strategies.append(tc)
        anchor = _nearest_anchor(el, same_frame)
        if anchor is not None:
            strategies.append(
                TargetStrategy(
                    kind="near_text",
                    value={"anchor": anchor.text, "role": "cell", "direction": "right_or_below"},
                    robustness="cell immediately right of a unique label cell; independent of the value",
                )
            )
        strategies.append(
            TargetStrategy(
                kind="css",
                value={"css": el.css},
                robustness="structural path; exact on an unchanged page",
            )
        )
        strategies.append(
            TargetStrategy(
                kind="bbox",
                value={"x": round(el.nbox[0], 4), "y": round(el.nbox[1], 4), "role": el.role},
                robustness="normalized position; last resort",
            )
        )
        return Target(
            description=_describe_cell(el, tc), frame=list(el.frame), strategies=strategies
        )

    def unique(pred: Callable[[Element], bool]) -> bool:
        return sum(1 for e in same_frame if pred(e)) == 1

    if el.name:
        strategies.append(
            TargetStrategy(
                kind="role_name",
                value={"role": el.role, "name": el.name},
                robustness=(
                    "accessible role+name; stable across layout and styling changes"
                    + (
                        ""
                        if unique(lambda e: e.role == el.role and e.name == el.name)
                        else " (NOT unique at record time — kept for cross-tenant hints only)"
                    )
                ),
            )
        )
    if el.label and el.interactive:
        strategies.append(
            TargetStrategy(
                kind="label",
                value={"label": el.label, "role": el.role},
                robustness="visible label in the same table row; survives DOM reshuffles",
            )
        )
    if el.name_attr:
        strategies.append(
            TargetStrategy(
                kind="name_attr",
                value={"name": el.name_attr, "tag": el.tag},
                robustness="form field name is bound to the server contract; rarely changes",
            )
        )
    if el.text and el.role in {"link", "button", "cell", "heading"}:
        strategies.append(
            TargetStrategy(
                kind="text",
                value={"text": el.text, "role": el.role},
                robustness="exact visible text; breaks only on copy changes",
            )
        )
    anchor = _nearest_anchor(el, same_frame)
    if anchor is not None:
        strategies.append(
            TargetStrategy(
                kind="near_text",
                value={"anchor": anchor.text, "role": el.role, "direction": "right_or_below"},
                robustness="first control of this role right of / below the anchor text",
            )
        )
    strategies.append(
        TargetStrategy(
            kind="css",
            value={"css": el.css},
            robustness="structural path; exact on an unchanged page, brittle to any DOM edit",
        )
    )
    strategies.append(
        TargetStrategy(
            kind="bbox",
            value={"x": round(el.nbox[0], 4), "y": round(el.nbox[1], 4), "role": el.role},
            robustness="normalized position; last resort and the only option for screenshots",
        )
    )
    return Target(description=_describe(el), frame=list(el.frame), strategies=strategies)


def resolve(target: Target, elements: list[Element]) -> Resolved:
    """Try strategies in order; the first that yields exactly one visible element wins.
    Ambiguity is an error, not a guess — acting on the wrong control in a bank system is
    worse than stopping."""
    candidates = [e for e in elements if e.frame == target.frame]
    if not candidates and target.frame:
        raise SurfaceError(f"frame {'/'.join(target.frame)} not present for {target.description!r}")
    ambiguous: list[str] = []
    for i, s in enumerate(target.strategies):
        matches = _match(s, candidates)
        if len(matches) == 1:
            return Resolved(element=matches[0], strategy_kind=s.kind, strategy_index=i)
        if len(matches) > 1:
            ambiguous.append(f"{s.kind} matched {len(matches)}")
    detail = f"; ambiguous: {', '.join(ambiguous)}" if ambiguous else ""
    raise SurfaceError(
        f"could not resolve {target.description!r}: no strategy matched exactly one element{detail}"
    )


def _match(s: TargetStrategy, els: list[Element]) -> list[Element]:
    v = s.value
    if s.kind == "role_name":
        return [e for e in els if e.role == v["role"] and _norm(e.name) == _norm(v["name"])]
    if s.kind == "label":
        return [
            e
            for e in els
            if e.interactive and e.role == v["role"] and _norm(e.label or "") == _norm(v["label"])
        ]
    if s.kind == "name_attr":
        return [e for e in els if e.name_attr == v["name"] and e.tag == v.get("tag", e.tag)]
    if s.kind == "text":
        return [e for e in els if e.role == v["role"] and _norm(e.text) == _norm(v["text"])]
    if s.kind == "near_text":
        anchors = [e for e in els if _norm(e.text) == _norm(v["anchor"]) and not e.interactive]
        if len(anchors) != 1:
            return []
        a = anchors[0]
        ax, ay = a.bbox[0] + a.bbox[2], a.bbox[1]
        pool = [
            e
            for e in els
            if e.role == v["role"]
            and (e.interactive or e.role == "cell")
            and e is not a
            and ((e.bbox[0] >= ax - 2 and _same_row(e, a)) or e.bbox[1] >= ay + a.bbox[3] - 2)
        ]
        # same-row candidates first (closest to the right), then the nearest below
        pool.sort(
            key=lambda e: (0 if _same_row(e, a) else 1, math.hypot(e.bbox[0] - ax, e.bbox[1] - ay))
        )
        return pool[:1]
    if s.kind == "table_cell":
        cells = (
            [e for e in els if e.role == "cell" and e.table == v["table"]]
            if v.get("table")
            else [e for e in els if e.role == "cell"]
        )
        tables = {e.table for e in cells}
        found: list[Element] = []
        for t in tables:
            tcells = [e for e in cells if e.table == t]
            headers = [e for e in tcells if _norm(e.text) == _norm(v["column_header"])]
            anchors = [e for e in tcells if _norm(e.text) == _norm(v["row_anchor"])]
            if len(headers) != 1 or len(anchors) != 1:
                continue
            found += [e for e in tcells if e.row == anchors[0].row and e.col == headers[0].col]
        return found
    if s.kind == "css":
        return [e for e in els if e.css == v["css"]]
    if s.kind == "bbox":
        pool = [e for e in els if e.role == v["role"]]
        if not pool:
            return []
        pool.sort(key=lambda e: math.hypot(e.nbox[0] - v["x"], e.nbox[1] - v["y"]))
        best = pool[0]
        return [best] if math.hypot(best.nbox[0] - v["x"], best.nbox[1] - v["y"]) < 0.05 else []
    raise ValueError(f"unknown strategy kind {s.kind!r}")


def _nearest_anchor(el: Element, els: list[Element]) -> Element | None:
    if not el.interactive and el.role != "cell":
        return None
    texts = [
        e
        for e in els
        if not e.interactive and e.text and e.role in {"cell", "text", "heading"} and e is not el
    ]
    if el.role == "cell" and el.table is not None:  # cells: only label cells in the same table row
        texts = [
            t
            for t in texts
            if t.role == "cell" and t.table == el.table and t.row == el.row and t.col < el.col
        ]
    best, best_d = None, 1e9
    for t in texts:
        if t.bbox[0] + t.bbox[2] <= el.bbox[0] + 2 and _same_row(t, el):
            d = el.bbox[0] - (t.bbox[0] + t.bbox[2])
            if d < best_d:
                best, best_d = t, d
    if best is not None and sum(1 for t in texts if _norm(t.text) == _norm(best.text)) == 1:
        return best
    return None


def _table_cell_strategy(el: Element, els: list[Element]) -> TargetStrategy | None:
    if el.table is None or el.row < 0:
        return None
    tcells = [e for e in els if e.role == "cell" and e.table == el.table]
    row_cells = sorted(
        (e for e in tcells if e.row == el.row and e.col != el.col), key=lambda e: e.col
    )
    anchor = next(
        (
            e
            for e in row_cells
            if e.text and sum(1 for x in tcells if _norm(x.text) == _norm(e.text)) == 1
        ),
        None,
    )

    def header_like(e: Element) -> bool:
        if e.tag == "th":
            return True
        row_cells = [x for x in tcells if x.row == e.row]
        return len(row_cells) > 1 and not any(any(ch.isdigit() for ch in x.text) for x in row_cells)

    header = next(
        (
            e
            for e in tcells
            if e.col == el.col
            and e.row < el.row
            and e.text
            and header_like(e)
            and sum(1 for x in tcells if _norm(x.text) == _norm(e.text)) == 1
        ),
        None,
    )
    if anchor is None or header is None:
        return None
    return TargetStrategy(
        kind="table_cell",
        value={"row_anchor": anchor.text, "column_header": header.text, "table": el.table},
        robustness="row label + column header; independent of the cell's value and of row order",
    )


def _describe_cell(el: Element, tc: TargetStrategy | None) -> str:
    if tc is not None:
        return f"cell '{tc.value['column_header']}' in row '{tc.value['row_anchor']}'"
    return f"cell right of '{el.label}'" if el.label else f"cell '{el.text}'"


def _same_row(a: Element, b: Element) -> bool:
    """Vertical overlap of the two boxes — robust to 18px table rows where a fixed tolerance is not."""
    return a.bbox[1] < b.bbox[1] + b.bbox[3] and a.bbox[1] + a.bbox[3] > b.bbox[1]


def _describe(el: Element) -> str:
    what = el.label or el.name or el.text or el.name_attr or el.tag
    return f"{el.role} '{what}'"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()

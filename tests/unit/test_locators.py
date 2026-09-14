from __future__ import annotations

import pytest

from glovebox.schema import Target, TargetStrategy
from glovebox.surface.base import Element, SurfaceError
from glovebox.surface.web import locators


def el(
    ref: str,
    role: str,
    name: str,
    *,
    text: str | None = None,
    label: str | None = None,
    name_attr: str | None = None,
    x: float = 0.0,
    y: float = 0.0,
    interactive: bool = True,
    tag: str = "input",
    table: str | None = None,
    row: int = -1,
    col: int = -1,
) -> Element:
    return Element(
        ref=ref,
        frame=["main"],
        role=role,
        name=name,
        text=text or name,
        label=label,
        name_attr=name_attr,
        tag=tag,
        css=f"#{ref}",
        bbox=(x, y, 50, 20),
        nbox=(x / 1000, y / 1000),
        interactive=interactive,
        table=table,
        row=row,
        col=col,
    )


def test_describe_orders_strategies_and_resolve_prefers_role_name() -> None:
    els = [
        el("e1", "cell", "Member No.", interactive=False, tag="td", x=0, y=100),
        el("e2", "textbox", "Member No.", label="Member No.", name_attr="member_no", x=100, y=100),
        el("e3", "button", "Find Member", tag="input", x=100, y=140),
    ]
    t = locators.describe(els[1], els)
    assert [s.kind for s in t.strategies] == [
        "role_name",
        "label",
        "name_attr",
        "near_text",
        "css",
        "bbox",
    ]
    r = locators.resolve(t, els)
    assert r.element.ref == "e2" and r.strategy_kind == "role_name"


def test_resolve_falls_through_when_label_renamed_across_tenant() -> None:
    t = Target(
        description="member input",
        frame=["main"],
        strategies=[
            TargetStrategy(
                kind="role_name", value={"role": "textbox", "name": "Member No."}, robustness=""
            ),
            TargetStrategy(
                kind="name_attr", value={"name": "member_no", "tag": "input"}, robustness=""
            ),
        ],
    )
    bravo = [el("e2", "textbox", "Member Number", label="Member Number", name_attr="member_no")]
    r = locators.resolve(t, bravo)
    assert r.strategy_kind == "name_attr"


def test_ambiguity_is_an_error_not_a_guess() -> None:
    t = Target(
        description="ok button",
        frame=["main"],
        strategies=[
            TargetStrategy(kind="role_name", value={"role": "button", "name": "OK"}, robustness="")
        ],
    )
    with pytest.raises(SurfaceError, match="ambiguous: role_name matched 2"):
        locators.resolve(t, [el("e1", "button", "OK"), el("e2", "button", "OK")])
    with pytest.raises(SurfaceError, match="no strategy matched"):
        locators.resolve(t, [el("e1", "button", "Cancel")])


def test_table_cell_strategy_is_value_independent() -> None:
    tbl = "body > table"
    cells = [
        el("h1", "cell", "Share", interactive=False, tag="td", table=tbl, row=0, col=0, x=0, y=0),
        el(
            "h2",
            "cell",
            "Current Balance",
            interactive=False,
            tag="td",
            table=tbl,
            row=0,
            col=1,
            x=100,
            y=0,
        ),
        el("r1", "cell", "S01", interactive=False, tag="td", table=tbl, row=1, col=0, x=0, y=20),
        el(
            "v1",
            "cell",
            "$10.00",
            interactive=False,
            tag="td",
            table=tbl,
            row=1,
            col=1,
            x=100,
            y=20,
        ),
    ]
    t = locators.describe(cells[3], cells)
    assert t.strategies[0].kind == "table_cell"
    assert t.strategies[0].value == {
        "row_anchor": "S01",
        "column_header": "Current Balance",
        "table": tbl,
    }
    later = [
        c
        if c.ref != "v1"
        else el(
            "v1",
            "cell",
            "$99.50",
            interactive=False,
            tag="td",
            table=tbl,
            row=1,
            col=1,
            x=100,
            y=20,
        )
        for c in cells
    ]
    assert locators.resolve(t, later).element.text == "$99.50"

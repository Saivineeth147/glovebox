"""Which locator strategies survive a change of surface, and which must refuse to guess."""

from __future__ import annotations

from glovebox.schema.capability import Target, TargetStrategy
from glovebox.surface.base import Element
from glovebox.surface.web import locators

FLAT = (0.0, 0.0, 0.0, 0.0)


def _cell(
    ref: str,
    text: str,
    row: int,
    col: int,
    table: str,
    geometry: tuple[float, float, float, float] = FLAT,
) -> Element:
    return Element(
        ref=ref,
        frame=[],
        role="cell",
        name=text,
        text=text,
        label=None,
        name_attr=None,
        tag="td",
        css=f"{table} td{ref}",
        bbox=geometry,
        nbox=(geometry[0], geometry[1]),
        interactive=False,
        page_box=geometry,
        table=table,
        row=row,
        col=col,
    )


def _share_table(table: str) -> list[Element]:
    return [
        _cell("h1", "Share", 0, 0, table),
        _cell("h2", "Description", 0, 1, table),
        _cell("h3", "Current Balance", 0, 2, table),
        _cell("r1", "S01", 1, 0, table),
        _cell("r2", "Regular Savings", 1, 1, table),
        _cell("r3", "$1250.75", 1, 2, table),
    ]


def test_should_find_the_cell_when_the_table_path_differs_between_surfaces() -> None:
    """A browser injects <tbody>; a parser does not. The row and column still identify the cell."""
    target = Target(
        description="cell 'Current Balance' in row 'S01'",
        strategies=[
            TargetStrategy(
                kind="table_cell",
                value={
                    "row_anchor": "S01",
                    "column_header": "Current Balance",
                    "table": "body > table:nth-of-type(2) > tbody > tr > td > table",
                },
                robustness="r",
            )
        ],
    )
    resolved = locators.resolve(target, _share_table("body > table:nth-of-type(2) > table"))
    assert resolved.element.text == "$1250.75"


def test_should_still_prefer_the_named_table_when_it_is_present() -> None:
    """Falling back must not make the strategy less precise where the path does match."""
    same = "t1"
    other = "t2"
    elements = [
        *_share_table(same),
        _cell("d1", "S01", 1, 0, other),
        _cell("d2", "Current Balance", 0, 2, other),
        _cell("d3", "$9.99", 1, 2, other),
    ]
    target = Target(
        description="balance",
        strategies=[
            TargetStrategy(
                kind="table_cell",
                value={"row_anchor": "S01", "column_header": "Current Balance", "table": same},
                robustness="r",
            )
        ],
    )
    assert locators.resolve(target, elements).element.text == "$1250.75"


def test_near_text_should_refuse_rather_than_guess_without_geometry() -> None:
    """With no layout engine every box is the origin, so ranking by distance is meaningless."""
    target = Target(
        description="cell right of 'S01'",
        strategies=[
            TargetStrategy(
                kind="near_text",
                value={"anchor": "S01", "role": "cell", "direction": "right_or_below"},
                robustness="r",
            )
        ],
    )
    from glovebox.surface.base import SurfaceError

    try:
        locators.resolve(target, _share_table("t1"))
    except SurfaceError:
        return
    raise AssertionError("near_text resolved an element using geometry it did not have")


def test_near_text_should_still_work_where_geometry_exists() -> None:
    anchor = _cell("a", "S01", 1, 0, "t1", (10.0, 50.0, 30.0, 12.0))
    right = _cell("b", "$1250.75", 1, 2, "t1", (90.0, 50.0, 40.0, 12.0))
    target = Target(
        description="cell right of 'S01'",
        strategies=[
            TargetStrategy(
                kind="near_text",
                value={"anchor": "S01", "role": "cell", "direction": "right_or_below"},
                robustness="r",
            )
        ],
    )
    assert locators.resolve(target, [anchor, right]).element.text == "$1250.75"

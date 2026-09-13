"""Parsing the target's pages into the same Element vocabulary the browser surface produces.

If the artifact's locator vocabulary is genuinely surface-agnostic, a parser with no browser
behind it can produce the same elements and the same capability can be replayed through it.
"""

from __future__ import annotations

from pathlib import Path

from glovebox.surface.http.page import parse_page

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "pages"


def _elements(name: str, frame: list[str] | None = None):
    return parse_page((PAGES / name).read_text(), frame or ["main"], "http://127.0.0.1:8089")


def test_should_find_the_login_fields_by_their_form_name() -> None:
    page = _elements("login.html")
    by_attr = {e.name_attr: e for e in page.elements if e.name_attr}
    assert by_attr["username"].role == "textbox"
    assert by_attr["password"].role == "textbox"


def test_should_read_the_label_from_the_cell_beside_the_field() -> None:
    """A legacy table form has no <label>; the operator reads the cell to its left."""
    page = _elements("login.html")
    username = next(e for e in page.elements if e.name_attr == "username")
    assert username.label == "Operator ID"


def test_should_expose_a_submit_button_by_its_value() -> None:
    page = _elements("login.html")
    assert any(e.role == "button" and e.name == "Sign In" for e in page.elements)


def test_should_expose_the_search_action_of_the_inquiry_form() -> None:
    page = _elements("member_search.html")
    assert any(e.role == "button" and e.name == "Find Member" for e in page.elements)


def test_should_address_a_balance_cell_by_its_row_and_column() -> None:
    """table_cell is the strategy that survived column reordering; it needs row/col here too."""
    page = _elements("member_detail.html")
    cells = [e for e in page.elements if e.role == "cell"]
    balance = next(e for e in cells if e.text == "$1250.75")
    row_codes = [e.text for e in cells if e.row == balance.row and e.table == balance.table]
    assert "S01" in row_codes


def test_should_expose_links_with_their_destination() -> None:
    page = _elements("member_detail.html")
    link = next(e for e in page.elements if e.role == "link" and e.name == "New Inquiry")
    assert link.href and link.href.endswith("/app/members/search")


def test_should_collect_the_form_that_submits_the_search() -> None:
    page = _elements("member_search.html")
    form = next(f for f in page.forms if "search" in f.action)
    assert form.method == "post" and "member_no" in form.fields


def test_should_report_the_pages_a_frameset_is_made_of() -> None:
    page = _elements("frameset.html", frame=[])
    assert [(f.name, f.src) for f in page.frames] == [
        ("nav", "/t/alpha/nav"),
        ("menu", "/t/alpha/menu"),
        ("main", "/t/alpha/app/login"),
    ]


def test_should_carry_the_visible_text_for_condition_checks() -> None:
    page = _elements("member_detail.html")
    assert "Share Accounts" in page.text and "Regular Savings" in page.text

"""Structural drift rewrites the page the way a real redesign would, without changing behaviour.

Each mutation is aimed at a different rung of the locator ladder, so a capability that still
replays afterwards did so because of the ladder rather than luck.
"""

from __future__ import annotations

from legacy_bank.drift import KNOWN_DRIFTS, apply_drift

SHARE_TABLE = (
    '<table class="frm" border="1"><tr><td colspan="3"><b>Share Accounts</b></td></tr>'
    '<tr bgcolor="#dddddd"><td>Share</td><td>Description</td>'
    '<td align="right">Current Balance</td></tr>'
    '<tr><td>S01</td><td>Regular Savings</td><td align="right">$1250.75</td></tr>'
    "</table>"
)
DETAIL_TABLE = (
    '<table class="frm"><tr><td>Member No.</td><td>100234</td>'
    "<td>Status</td><td>Active</td></tr></table>"
)
SEARCH_FORM = '<input type="submit" value="Find Member">'


def test_should_return_the_page_unchanged_when_nothing_is_armed() -> None:
    assert apply_drift(SHARE_TABLE, []) == SHARE_TABLE


def test_should_rename_the_search_action_to_wording_no_tenant_uses() -> None:
    out = apply_drift(SEARCH_FORM, ["rename_action"])
    assert "Find Member" not in out and "Locate Member" in out


def test_should_rename_the_member_field_label() -> None:
    out = apply_drift(DETAIL_TABLE, ["rename_label"])
    assert "Member No." not in out and "Member Ref." in out


def test_should_swap_the_description_and_balance_columns() -> None:
    """table_cell addresses a cell by column header, so it should survive this; css cannot."""
    out = apply_drift(SHARE_TABLE, ["reorder_columns"])
    header = out[out.index("<tr bgcolor") : out.index("</tr>", out.index("<tr bgcolor"))]
    assert header.index("Current Balance") < header.index("Description")
    assert "$1250.75" in out and "Regular Savings" in out


def test_should_leave_tables_outside_share_accounts_alone_when_reordering() -> None:
    out = apply_drift(DETAIL_TABLE + SHARE_TABLE, ["reorder_columns"])
    assert DETAIL_TABLE in out


def test_should_wrap_every_table_so_structural_css_paths_break() -> None:
    out = apply_drift(SHARE_TABLE, ["wrap_tables"])
    assert out.count("<div class=") == out.count("</table>") == 1
    assert out.startswith("<div class=")


def test_should_insert_a_leading_table_so_nth_of_type_paths_shift() -> None:
    out = apply_drift(SHARE_TABLE, ["insert_leading_table"])
    assert out.index("<table") < out.index("Share Accounts")
    assert out.count("<table") == 2


def test_should_apply_several_mutations_together() -> None:
    out = apply_drift(SEARCH_FORM + SHARE_TABLE, ["rename_action", "wrap_tables"])
    assert "Locate Member" in out and "<div class=" in out


def test_should_reject_an_unknown_mutation_rather_than_silently_doing_nothing() -> None:
    import pytest

    with pytest.raises(KeyError):
        apply_drift(SHARE_TABLE, ["no_such_drift"])


def test_every_known_drift_documents_which_locator_it_attacks() -> None:
    assert KNOWN_DRIFTS and all(len(v) > 20 for v in KNOWN_DRIFTS.values())


def test_should_insert_the_spacer_inside_body_so_the_document_stays_valid() -> None:
    out = apply_drift("<html><body><p>hi</p></body></html>", ["insert_leading_table"])
    assert out.index("<body>") < out.index("drift-spacer") < out.index("<p>")


def test_should_leave_a_frameset_document_untouched() -> None:
    """Content before a frameset makes the browser discard the frames: that is corruption,
    not a redesign, and the frameset page has no addressable control anyway."""
    frameset = '<html><frameset rows="60,*"><frame name="nav"></frameset></html>'
    assert apply_drift(frameset, list(KNOWN_DRIFTS)) == frameset

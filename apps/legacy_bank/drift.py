"""Structural drift: presentation-only rewrites of a rendered page.

Fault injection answers "what does replay do when the app misbehaves". This answers the
question a reviewer asks next: what does it do when the app is *redesigned*. Each mutation
changes how a control is addressed without changing what the app does, and each is aimed at a
different rung of the locator ladder, so the survival of a capability becomes evidence about
the ladder rather than an anecdote.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

# Wording no tenant uses, so a survivor cannot be explained by the tenant override path.
RENAMED_ACTION = "Locate Member"
RENAMED_LABEL = "Member Ref."
WRAPPER_OPEN = '<div class="drift-wrap">'
_SHARE_ACCOUNTS_MARKER = "Share Accounts"
_THREE_CELL_ROW = re.compile(
    r"(<tr[^>]*>)(<td[^>]*>.*?</td>)(<td[^>]*>.*?</td>)(<td[^>]*>.*?</td>)(</tr>)"
)


def _rename_action(html: str) -> str:
    return (
        html.replace("Find Member", RENAMED_ACTION)
        .replace(">Search<", f">{RENAMED_ACTION}<")
        .replace('value="Search"', f'value="{RENAMED_ACTION}"')
    )


def _rename_label(html: str) -> str:
    return html.replace("Member No.", RENAMED_LABEL).replace("Member Number", RENAMED_LABEL)


def _reorder_columns(html: str) -> str:
    """Swap the description and balance columns of the Share Accounts table only.

    Scoped to that one table so the member detail grid, which a capability also reads, is
    left as a control: a failure here is attributable to the column move.
    """
    start = html.find(_SHARE_ACCOUNTS_MARKER)
    if start == -1:
        return html
    end = html.find("</table>", start)
    if end == -1:
        return html
    region = html[start:end]
    swapped = _THREE_CELL_ROW.sub(r"\1\2\4\3\5", region)
    return html[:start] + swapped + html[end:]


def _wrap_tables(html: str) -> str:
    """Nesting stays balanced: each <table> gains an opener and each </table> a closer."""
    return html.replace("<table", f"{WRAPPER_OPEN}<table").replace("</table>", "</table></div>")


_SPACER_TABLE = '<table class="drift-spacer"><tr><td></td></tr></table>'
_BODY_TAG = re.compile(r"<body[^>]*>", re.IGNORECASE)


def _insert_leading_table(html: str) -> str:
    """Shifts every `body > table:nth-of-type(N)` path by one, and nothing else.

    Inserted inside <body>, not before the document: content ahead of <html> changes how the
    page parses, which breaks the app rather than redesigning it.
    """
    body = _BODY_TAG.search(html)
    if body is None:
        return _SPACER_TABLE + html
    return html[: body.end()] + _SPACER_TABLE + html[body.end() :]


KNOWN_DRIFTS: dict[str, str] = {
    "rename_action": "renames the search button; attacks role_name and text locators",
    "rename_label": "renames the member field label; attacks label and near_text locators",
    "reorder_columns": "swaps two columns of the Share Accounts table; attacks css paths, "
    "while table_cell addresses by column header and should survive",
    "wrap_tables": "wraps every table in a div; attacks structural css paths",
    "insert_leading_table": "adds a table before the page content; shifts every nth-of-type "
    "css path by one",
}

_MUTATIONS: dict[str, Callable[[str], str]] = {
    "rename_action": _rename_action,
    "rename_label": _rename_label,
    "reorder_columns": _reorder_columns,
    "wrap_tables": _wrap_tables,
    "insert_leading_table": _insert_leading_table,
}


def apply_drift(html: str, armed: Iterable[str]) -> str:
    """Apply each armed mutation in turn. An unknown name raises rather than doing nothing.

    A frameset document is returned untouched: it holds no addressable control, and anything
    inserted around a frameset stops the frames loading at all, which would measure the
    mutation rather than the capability.
    """
    names = list(armed)
    for name in names:
        if name not in _MUTATIONS:
            raise KeyError(name)
    if "<frameset" in html.lower():
        return html
    for name in names:
        html = _MUTATIONS[name](html)
    return html

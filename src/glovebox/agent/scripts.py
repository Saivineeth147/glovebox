"""Offline discovery scripts for the ScriptedLLM (tests, CI, `--offline` demos).

Each script is what a competent model is expected to do for a goal against Meridian Core.
They are *not* used in the real discovery run — that is the live model's job — but they keep
every other part of the system testable without a key."""

from __future__ import annotations

from typing import Any

MEMBER_SAVINGS_BALANCE: list[dict[str, Any]] = [
    {"tool": "observe", "input": {}},
    {
        "tool": "fill",
        "find": {"name_attr": "username"},
        "input": {"param": "username", "why": "sign in as the operator"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "password"},
        "input": {"param": "password", "why": "enter operator password"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Sign In"},
        "input": {"why": "submit the sign-in form"},
    },
    {"tool": "assert_text", "input": {"text": "Welcome, ", "why": "confirm we are signed in"}},
    {
        "tool": "click",
        "find": {"role": "link", "name": "Member Inquiry", "frame": ["menu"]},
        "input": {"why": "open the member inquiry screen"},
    },
    {
        "tool": "assert_text",
        "input": {"text": "Member Inquiry", "why": "confirm the inquiry form is shown"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "member_no"},
        "input": {"param": "member_id", "why": "enter the member number"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Find Member"},
        "input": {"why": "run the search"},
    },
    {
        "tool": "assert_text",
        "input": {"text": "Share Accounts", "why": "confirm the member detail page loaded"},
    },
    # Go and read the wording of the not-found screen rather than guessing it, then come back.
    # Nothing between begin_probe and end_probe is recorded, so the capability does not end up
    # searching for a member who does not exist.
    {"tool": "begin_probe", "input": {"why": "read the exact wording of the not-found screen"}},
    {
        "tool": "click",
        "find": {"role": "link", "name": "New Inquiry"},
        "input": {"why": "start a fresh inquiry"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "member_no"},
        "input": {"text": "999999", "why": "search for a member number that does not exist"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Find Member"},
        "input": {"why": "reach the not-found screen"},
    },
    {
        "tool": "click",
        "find": {"role": "link", "name": "Back to search"},
        "input": {"why": "return towards the recorded flow"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "member_no"},
        "input": {"param": "member_id", "why": "restore the member the goal is about"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Find Member"},
        "input": {"why": "return to the member detail screen"},
    },
    {"tool": "end_probe", "input": {}},
    {
        "tool": "declare_outcome",
        "input": {
            "code": "MEMBER_NOT_FOUND",
            "description": "No member record matched the number",
            "detect_text": "No member record matched",
        },
    },
    {
        "tool": "extract",
        "find": {"role": "cell", "text": "$1250.75"},
        "input": {
            "output": "savings_balance",
            "description": "Current balance of the S01 Regular Savings share, USD",
            "type": "number",
        },
    },
    {
        "tool": "extract",
        "find": {"role": "cell", "text": "Doe, Jane"},
        "input": {"output": "member_name", "description": "Member name as 'Last, First'"},
    },
    {
        "tool": "finish",
        "input": {
            "success_text": ["Share Accounts", "Regular Savings"],
            "summary": "Look up a member by number and read the current balance of their Regular Savings share.",
            "title": "Member savings balance lookup",
            "parameter_descriptions": {
                "member_id": "Member number to look up",
                "username": "Operator ID for the back-office sign-in",
                "password": "Operator password",
            },
        },
    },
]

OPEN_SUB_ACCOUNT: list[dict[str, Any]] = [
    {"tool": "observe", "input": {}},
    {
        "tool": "fill",
        "find": {"name_attr": "username"},
        "input": {"param": "username", "why": "sign in"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "password"},
        "input": {"param": "password", "why": "password"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Sign In"},
        "input": {"why": "submit sign-in"},
    },
    {"tool": "assert_text", "input": {"text": "Welcome, ", "why": "signed in"}},
    {
        "tool": "click",
        "find": {"role": "link", "name": "Member Inquiry", "frame": ["menu"]},
        "input": {"why": "open inquiry"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "member_no"},
        "input": {"param": "member_id", "why": "member number"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Find Member"},
        "input": {"why": "search"},
    },
    {"tool": "assert_text", "input": {"text": "Member Detail", "why": "member found"}},
    {
        "tool": "declare_outcome",
        "input": {
            "code": "MEMBER_NOT_FOUND",
            "description": "No member record matched the number",
            "detect_text": "No member record matched",
        },
    },
    {
        "tool": "click",
        "find": {"role": "link", "name": "Open Sub-Account"},
        "input": {"why": "open the sub-account form"},
    },
    {"tool": "assert_text", "input": {"text": "Open Sub-Account", "why": "form shown"}},
    {
        "tool": "select",
        "find": {"name_attr": "product"},
        "input": {"param": "product", "why": "choose product"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "nickname"},
        "input": {"param": "nickname", "why": "nickname"},
    },
    {
        "tool": "declare_outcome",
        "input": {
            "code": "ACCESS_DENIED",
            "description": "Operator role may not open sub-accounts for this member",
            "detect_text": "Access denied",
        },
    },
    {
        "tool": "declare_outcome",
        "input": {
            "code": "VALIDATION_ERROR",
            "description": "The form rejected the submitted values",
            "detect_text": "Nickname is required",
        },
    },
    {
        "tool": "expect_dialog",
        "input": {"response": "accept", "why": "the app confirms before creating the share"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Open Account"},
        "input": {
            "why": "submit the new sub-account (creates a share record)",
            "risk": "irreversible",
        },
    },
    {"tool": "assert_text", "input": {"text": "Sub-Account Opened", "why": "confirmation screen"}},
    {
        "tool": "extract",
        "find": {"role": "cell", "col": 1, "row": 1},
        "input": {
            "output": "reference",
            "description": "Reference number of the newly opened sub-account",
        },
    },
    {
        "tool": "finish",
        "input": {
            "success_text": ["Sub-Account Opened"],
            "title": "Open member sub-account",
            "summary": "Open a new sub-account (share) for a member and reach the confirmation screen.",
            "parameter_descriptions": {
                "member_id": "Member number",
                "product": "Share product name",
                "nickname": "Nickname for the new share",
                "username": "Operator ID",
                "password": "Operator password",
            },
        },
    },
    # ACCESS_DENIED and VALIDATION_ERROR need states this operator cannot reach while
    # recording — one needs a permission they do not have, the other a dialog dance that would
    # land in the capability. The first finish is refused with that nudge; this second one
    # accepts them unverified and leaves the judgement to approval.
    {
        "tool": "finish",
        "input": {
            "success_text": ["Sub-Account Opened"],
            "title": "Open member sub-account",
            "summary": "Open a new sub-account (share) for a member and reach the confirmation screen.",
            "parameter_descriptions": {
                "member_id": "Member number",
                "product": "Share product name",
                "nickname": "Nickname for the new share",
                "username": "Operator ID",
                "password": "Operator password",
            },
        },
    },
]


#: A second read-only flow over the same screens, reading the identity grid rather than the
#: share table. It exists so the catalog is a portfolio: drift evaluation over one capability
#: says something about one capability, and resilience is a property of the set.
MEMBER_STATUS: list[dict[str, Any]] = [
    {"tool": "observe", "input": {}},
    {
        "tool": "fill",
        "find": {"name_attr": "username"},
        "input": {"param": "username", "why": "sign in as the operator"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "password"},
        "input": {"param": "password", "why": "enter operator password"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Sign In"},
        "input": {"why": "submit the sign-in form"},
    },
    {
        "tool": "click",
        "find": {"role": "link", "name": "Member Inquiry", "frame": ["menu"]},
        "input": {"why": "open the member inquiry screen"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "member_no"},
        "input": {"param": "member_id", "why": "enter the member number"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Find Member"},
        "input": {"why": "run the search"},
    },
    {
        "tool": "assert_text",
        "input": {"text": "Member Detail", "why": "confirm the member detail page loaded"},
    },
    {"tool": "begin_probe", "input": {"why": "read the exact wording of the not-found screen"}},
    {
        "tool": "click",
        "find": {"role": "link", "name": "New Inquiry"},
        "input": {"why": "start a fresh inquiry"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "member_no"},
        "input": {"text": "999999", "why": "search for a member number that does not exist"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Find Member"},
        "input": {"why": "reach the not-found screen"},
    },
    {
        "tool": "click",
        "find": {"role": "link", "name": "Back to search"},
        "input": {"why": "return towards the recorded flow"},
    },
    {
        "tool": "fill",
        "find": {"name_attr": "member_no"},
        "input": {"param": "member_id", "why": "restore the member the goal is about"},
    },
    {
        "tool": "click",
        "find": {"role": "button", "name": "Find Member"},
        "input": {"why": "return to the member detail screen"},
    },
    {"tool": "end_probe", "input": {}},
    {
        "tool": "declare_outcome",
        "input": {
            "code": "MEMBER_NOT_FOUND",
            "description": "No member record matched the number",
            "detect_text": "No member record matched",
        },
    },
    {
        "tool": "extract",
        "find": {"role": "cell", "text": "Doe, Jane"},
        "input": {"output": "member_name", "description": "Member name as 'Last, First'"},
    },
    {
        "tool": "extract",
        "find": {"role": "cell", "text": "Active"},
        "input": {
            "output": "member_status",
            "description": "Membership status shown on the record",
        },
    },
    {
        "tool": "finish",
        "input": {
            "success_text": ["Member Detail", "Status"],
            "summary": "Look up a member by number and read their name and membership status.",
            "title": "Member status lookup",
            "parameter_descriptions": {"member_id": "Member number to look up"},
        },
    },
]


SCRIPTS = {
    "member_savings_balance": MEMBER_SAVINGS_BALANCE,
    "member_status": MEMBER_STATUS,
    "open_sub_account": OPEN_SUB_ACCOUNT,
}


def standard_params(app_url: str) -> dict[str, Any]:
    """Parameter specs + values every Meridian Core capability shares (credentials from env)."""
    import os

    from glovebox.schema.capability import Parameter, ParamType

    specs = [
        Parameter(
            name="username", type=ParamType.STRING, description="Operator ID", sensitive=True
        ),
        Parameter(
            name="password", type=ParamType.STRING, description="Operator password", sensitive=True
        ),
    ]
    values = {
        "username": os.environ.get("GLOVEBOX_APP_USERNAME", "teller1"),
        "password": os.environ.get("GLOVEBOX_APP_PASSWORD", "teller1-pass"),
    }
    return {"specs": specs, "values": values, "entry": app_url.rstrip("/") + "/t/alpha/"}

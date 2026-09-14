"""The unverified-outcome refusal has to live where every caller passes, not in one command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from glovebox.catalog import Catalog
from glovebox.catalog.registry import UnverifiedOutcomeError
from glovebox.schema.capability import Capability

ROOT = Path(__file__).resolve().parents[2]


def _catalog_with_unverified(tmp_path: Path) -> Catalog:
    doc = json.loads((ROOT / "capabilities" / "member_savings_balance.json").read_text())
    doc["review"] = {"status": "draft", "replays": 0, "replay_successes": 0}
    doc["outcomes"] = [
        {
            "code": "MEMBER_NOT_FOUND",
            "description": "no match",
            "detect": {"kind": "text_visible", "value": "No member found", "timeout_ms": 0},
            "terminal": True,
            "verified": False,
        }
    ]
    catalog = Catalog(tmp_path)
    catalog.save(Capability.model_validate(doc))
    return catalog


def test_should_refuse_approval_of_an_unverified_terminal_outcome(tmp_path: Path) -> None:
    catalog = _catalog_with_unverified(tmp_path)
    with pytest.raises(UnverifiedOutcomeError, match="MEMBER_NOT_FOUND"):
        catalog.approve("member_savings_balance", "admin@example.com")


def test_should_allow_approval_when_the_reviewer_accepts_it_explicitly(tmp_path: Path) -> None:
    catalog = _catalog_with_unverified(tmp_path)
    approved = catalog.approve(
        "member_savings_balance", "admin@example.com", accept_unverified=True
    )
    assert approved.review.status == "approved"


def test_should_refuse_through_the_studio_endpoint_too(tmp_path: Path) -> None:
    """The CLI had the guard and Studio did not, so an admin could click past it."""
    from fastapi.testclient import TestClient

    from glovebox.studio.server import create_studio

    _catalog_with_unverified(tmp_path)
    app = create_studio(tmp_path / "runs", tmp_path, ROOT / "policies" / "default.yaml")
    client = TestClient(app)
    client.post(
        "/api/auth/register",
        json={"email": "admin@example.com", "password": "a-long-enough-password"},
    )

    refused = client.post("/api/capabilities/member_savings_balance/approve", json={})
    assert refused.status_code == 409 and "MEMBER_NOT_FOUND" in refused.text

    accepted = client.post(
        "/api/capabilities/member_savings_balance/approve", json={"accept_unverified": True}
    )
    assert accepted.status_code == 200


def test_one_unloadable_artifact_should_not_take_down_the_whole_catalog(tmp_path: Path) -> None:
    """Catalog.all backs the listing page and the CLI; one bad file must not 500 both."""
    catalog = _catalog_with_unverified(tmp_path)
    (tmp_path / "broken.json").write_text('{"id": "broken", "not": "a capability"}')

    listed = catalog.all()

    assert [c.id for c in listed] == ["member_savings_balance"]
    assert [name for name, _ in catalog.problems()] == ["broken"]


def test_the_drift_gate_should_skip_a_capability_no_one_has_approved(tmp_path: Path) -> None:
    """The sweep fails CI, so it must not fail it on an artifact nobody has accepted yet.

    Four places in the documentation say the sweep covers "every approved capability"; before
    this it loaded the whole directory and replayed drafts with the gate disabled.
    """
    from typer.testing import CliRunner

    from glovebox import cli

    doc = json.loads((ROOT / "capabilities" / "member_savings_balance.json").read_text())
    doc["review"]["status"] = "draft"
    (tmp_path / "member_savings_balance.json").write_text(json.dumps(doc))

    result = CliRunner().invoke(cli.app, ["drift", "--catalog-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "no approved capabilities" in result.output

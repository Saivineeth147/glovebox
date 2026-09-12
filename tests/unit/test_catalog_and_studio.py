from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from glovebox.catalog import Catalog
from glovebox.schema import Capability, Provenance
from glovebox.studio.server import create_studio
from tests.unit.test_schema import _cap

ROOT = Path(__file__).resolve().parents[2]


def test_catalog_bumps_version_on_rerecord_and_resets_review(tmp_path: Path):
    cat = Catalog(tmp_path)
    first = _cap()
    cat.save(first)
    cat.approve("demo", "reviewer")
    assert cat.load("demo").review.status == "approved"
    again = _cap(
        provenance=Provenance(
            discovery_run_id="r2",
            recorded_at="2026-01-02T00:00:00Z",
            model="m",
            surface="s",
            transcript_sha256="1" * 64,
        )
    )
    cat.save(again)
    saved = cat.load("demo")
    assert saved.version == "1.0.1" and saved.review.status == "draft"
    cat.record_replay("demo", True)  # bookkeeping never bumps
    assert cat.load("demo").version == "1.0.1" and cat.load("demo").review.replays == 1


def test_studio_api_serves_catalog_policy_and_tools(tmp_path: Path):
    cat_dir = tmp_path / "caps"
    Catalog(cat_dir).save(_cap())
    app = create_studio(tmp_path / "runs", cat_dir, ROOT / "policies" / "default.yaml")
    c = TestClient(app)
    # The API is gated, so an unauthenticated caller sees nothing at all.
    assert c.get("/api/overview").status_code == 401
    # The first account registered is the admin, and registering signs it in.
    assert (
        c.post(
            "/api/auth/register",
            json={"email": "reviewer@example.com", "password": "a-long-enough-password"},
        ).json()["role"]
        == "admin"
    )
    ov = c.get("/api/overview").json()
    assert ov["capabilities"] == 1 and ov["policy"] == "meridian-core-teller" and "target" in ov
    caps = c.get("/api/capabilities").json()
    assert caps[0]["id"] == "demo" and caps[0]["confidence"] is None
    assert c.get("/api/capabilities/tools").json()[0]["name"] == "demo"
    assert c.get("/api/capabilities/nope").status_code == 404
    pol = c.get("/api/policy").json()
    assert "allowed_origins" in pol["policy"] and pol["raw"].startswith("#")
    approved = c.post("/api/capabilities/demo/approve", json={"reviewer": "qa"}).json()
    assert approved["review"]["status"] == "approved"
    assert c.get("/api/runs").json() == []
    assert c.get("/api/runs/nope").status_code == 404
    assert c.get("/api/jobs").json() == []
    index = c.get("/")
    assert index.status_code in (200, 503)


def test_committed_capability_is_valid_and_approved():
    cap = Capability.model_validate_json(
        (ROOT / "capabilities" / "member_savings_balance.json").read_text()
    )
    assert cap.review.status == "approved"
    assert cap.steps[0].value == "{{ app.entry_path }}"

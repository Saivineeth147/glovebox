"""The agent-facing capability catalog: list it, export it as tool definitions, approve it.

Split out of `cli.py` so that file stays reviewable; these three commands are one subject and
change together.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

catalog_cli = typer.Typer(help="Capability catalog.")


@catalog_cli.command("list")
def catalog_list(catalog_dir: Path = Path("capabilities")) -> None:
    from glovebox.catalog import Catalog

    t = Table("id", "version", "status", "risk", "inputs", "outputs", "confidence", "title")
    for c in Catalog(catalog_dir).all():
        conf = c.review.confidence
        t.add_row(
            c.id,
            c.version,
            str(c.review.status),
            str(c.max_risk),
            ", ".join(p.name for p in c.inputs),
            ", ".join(o.name for o in c.outputs),
            "-" if conf is None else f"{conf:.0%} ({c.review.replays})",
            c.title,
        )
    rprint(t)


@catalog_cli.command("tools")
def catalog_tools(catalog_dir: Path = Path("capabilities"), include_drafts: bool = False) -> None:
    """Print the catalog as Claude tool definitions an agent can call."""
    from glovebox.catalog import Catalog

    print(json.dumps(Catalog(catalog_dir).tool_definitions(include_drafts), indent=2))


@catalog_cli.command("approve")
def catalog_approve(
    capability_id: str,
    reviewer: str,
    notes: str | None = None,
    catalog_dir: Path = Path("capabilities"),
    accept_unverified: bool = False,
) -> None:
    """Approve a capability for unattended replay.

    Refuses an unverified terminal outcome by default: its detector is wording the run never
    saw, so it never fires and the capability reports a hard failure where the catalog
    promised a business outcome. Pass --accept-unverified to approve it anyway.
    """
    from glovebox.catalog import Catalog
    from glovebox.catalog.registry import UnverifiedOutcomeError

    try:
        c = Catalog(catalog_dir).approve(capability_id, reviewer, notes, accept_unverified)
    except UnverifiedOutcomeError as refusal:
        rprint(
            f"[red]refusing to approve {capability_id}[/red]: {refusal}. Re-record having "
            "exercised that state, or approve with --accept-unverified."
        )
        raise typer.Exit(code=1) from refusal
    rprint(f"{c.id}@{c.version} approved by {reviewer}")

"""Glovebox command line.

glovebox target serve                 run the simulated legacy app
glovebox discover ...                 LLM-driven discovery → capability artifact
glovebox replay <cap> --param k=v     deterministic replay (the production path)
glovebox catalog list|tools|approve   the agent-facing capability catalog
glovebox stability <cap> --runs N     replay N times, report flakiness
glovebox validate <cap.json>          schema-check an artifact
glovebox schema                       print the JSON Schema of the artifact
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import print as rprint
from rich.table import Table

from glovebox.schema.capability import Capability, Parameter, ParamType
from glovebox.schema.policy import Policy

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
target_cli = typer.Typer(help="Simulated legacy target app (Meridian Core).")
catalog_cli = typer.Typer(help="Capability catalog.")
app.add_typer(target_cli, name="target")
app.add_typer(catalog_cli, name="catalog")

DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "policies" / "default.yaml"


def _kv(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise typer.BadParameter(f"expected name=value, got {item!r}")
        k, v = item.split("=", 1)
        out[k] = v
    return out


def _params(
    param: list[str] | None, secret: list[str] | None
) -> tuple[dict[str, Any], list[Parameter]]:
    """--param name=value (plain) and --secret name=ENV_VAR (sensitive, read from env)."""
    values: dict[str, Any] = {}
    specs: list[Parameter] = []
    for k, v in _kv(param).items():
        values[k] = v
        specs.append(Parameter(name=k, type=ParamType.STRING, description=f"Input parameter {k}"))
    for k, env in _kv(secret).items():
        if env not in os.environ:
            raise typer.BadParameter(f"secret {k}: environment variable {env} is not set")
        values[k] = os.environ[env]
        specs.append(
            Parameter(
                name=k, type=ParamType.STRING, description=f"Sensitive input {k}", sensitive=True
            )
        )
    return values, specs


def _policy(path: Path | None) -> Policy:
    return Policy.load(path or DEFAULT_POLICY)


def _bridge(console_port: int | None) -> Any:
    if console_port is None:
        return None, None
    from glovebox.control.console import OperatorConsole
    from glovebox.control.session import OperatorBridge

    bridge = OperatorBridge()
    console = OperatorConsole(bridge, port=console_port).start()
    rprint(f"[bold]Operator console:[/bold] {console.url}")
    return bridge, console


# ----------------------------------------------------------------------------- target
@target_cli.command("serve")
def target_serve(port: int = 8089, host: str = "127.0.0.1") -> None:
    """Run Meridian Core (the simulated hostile back-office app)."""
    import uvicorn

    from legacy_bank import create_app

    rprint(
        f"Meridian Core on http://{host}:{port}/  (tenants: /t/alpha/, /t/bravo/; faults: /__sim/faults)"
    )
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


# ----------------------------------------------------------------------------- studio
@app.command()
def studio(
    port: int = 8800,
    host: str = "127.0.0.1",
    runs_dir: Path = Path("runs"),
    catalog_dir: Path = Path("capabilities"),
    policy: Path | None = None,
) -> None:
    """Run Glovebox Studio: the workspace UI (runs, live agent view, catalog, takeover, policy)."""
    import uvicorn

    from glovebox.studio.server import create_studio

    runs_dir.mkdir(parents=True, exist_ok=True)
    rprint(f"[bold]Glovebox Studio[/bold] on http://{host}:{port}/   (API docs: /api/docs)")
    uvicorn.run(
        create_studio(runs_dir, catalog_dir, policy or DEFAULT_POLICY),
        host=host,
        port=port,
        log_level="warning",
    )


# ----------------------------------------------------------------------------- discover
@app.command()
def discover(
    goal: Annotated[str, typer.Option(help="Natural-language goal.")],
    app_url: Annotated[str, typer.Option(help="Entry URL of the target application.")],
    capability_name: Annotated[str, typer.Option(help="Stable id for the recorded capability.")],
    param: Annotated[list[str] | None, typer.Option(help="name=value input parameter.")] = None,
    secret: Annotated[
        list[str] | None, typer.Option(help="name=ENV_VAR sensitive parameter.")
    ] = None,
    app_id: str = "meridian-core",
    tenant: str | None = "alpha",
    policy: Path | None = None,
    model: str | None = None,
    provider: Annotated[
        str | None, typer.Option(help="anthropic | openrouter | openai (default: from env keys)")
    ] = None,
    offline_script: Annotated[
        str | None, typer.Option(help="Use a scripted policy instead of the model (name or path).")
    ] = None,
    catalog_dir: Path = Path("capabilities"),
    runs_dir: Path = Path("runs"),
    evidence_dir: Path | None = None,
    console_port: int | None = 8790,
    max_steps: int | None = None,
    headed: bool = False,
    no_screenshots: bool = False,
) -> None:
    """Run the LLM-driven observe→decide→act loop and record a capability artifact."""
    from glovebox.runner import run_discovery

    values, specs = _params(param, secret)
    if not secret:  # default operator credentials from env (never persisted)
        from glovebox.agent.scripts import standard_params

        std = standard_params(app_url)
        specs = [*std["specs"], *specs]
        values = {**std["values"], **values}
    pol = _policy(policy)
    bridge, console = _bridge(console_port)

    if offline_script:
        from glovebox.agent.llm import ScriptedLLM
        from glovebox.agent.scripts import SCRIPTS

        script = (
            SCRIPTS[offline_script]
            if offline_script in SCRIPTS
            else json.loads(Path(offline_script).read_text())
        )
        rprint("[yellow]offline mode: scripted decisions, no model[/yellow]")

        def llm_factory(obs: Any) -> Any:
            return ScriptedLLM(script, obs)
    else:
        from glovebox.agent.llm import make_llm

        llm = make_llm(model, provider)
        rprint(f"model: [bold]{llm.name}[/bold]")

        def llm_factory(obs: Any) -> Any:
            return llm

    res = run_discovery(
        goal=goal,
        entry_url=app_url if "/t/" in app_url else app_url.rstrip("/") + f"/t/{tenant}/",
        params=values,
        param_specs=specs,
        llm_factory=llm_factory,
        policy=pol,
        capability_id=capability_name,
        app_id=app_id,
        tenant=tenant,
        runs_dir=runs_dir,
        bridge=bridge,
        headless=not headed,
        echo=True,
        max_steps=max_steps,
        screenshots=not no_screenshots,
    )
    if console:
        console.stop()
    rprint(
        f"\n[bold]discovery {res.status}[/bold]: {res.summary}  ({res.steps} actions)  evidence: {res.evidence_dir}"
    )
    if res.capability:
        from glovebox.catalog import Catalog

        p = Catalog(catalog_dir).save(res.capability)
        rprint(f"capability saved: {p}  (status: draft — approve before unattended replay)")
    if evidence_dir:
        _copy_evidence(res.evidence_dir, evidence_dir)
    raise typer.Exit(0 if res.status == "success" else 1)


# ----------------------------------------------------------------------------- replay
@app.command()
def replay(
    capability: Annotated[str, typer.Argument(help="Capability id (in catalog) or path to .json")],
    param: Annotated[list[str] | None, typer.Option(help="name=value input parameter.")] = None,
    secret: Annotated[
        list[str] | None, typer.Option(help="name=ENV_VAR sensitive parameter.")
    ] = None,
    tenant: str | None = None,
    policy: Path | None = None,
    catalog_dir: Path = Path("capabilities"),
    runs_dir: Path = Path("runs"),
    evidence_dir: Path | None = None,
    attended: Annotated[
        bool, typer.Option(help="A human is reachable via the operator console.")
    ] = False,
    console_port: int | None = None,
    allow_draft: bool = False,
    headed: bool = False,
    fault: Annotated[
        list[str] | None, typer.Option(help="Arm a simulated fault on the target before replay.")
    ] = None,
    handoff_timeout: float = 300.0,
) -> None:
    """Deterministically replay a capability with input parameters (no model involved)."""
    from glovebox.catalog import Catalog
    from glovebox.runner import run_replay

    cat = Catalog(catalog_dir)
    cap = cat.load(capability)
    values, _ = _params(param, secret)
    for p in cap.inputs:
        if p.sensitive and p.name not in values:
            env = f"GLOVEBOX_APP_{p.name.upper()}"
            if env in os.environ:
                values[p.name] = os.environ[env]
    pol = _policy(policy)
    bridge, console = _bridge(console_port if (attended or console_port) else None)
    if fault:
        import httpx

        for f in fault:
            httpx.post(f"{cap.app.origin}/__sim/faults/{f}", timeout=5).raise_for_status()
            rprint(f"[yellow]armed simulated fault: {f}[/yellow]")
    res = run_replay(
        cap,
        values,
        pol,
        runs_dir=runs_dir,
        tenant=tenant,
        bridge=bridge,
        attended=attended or bridge is not None,
        allow_draft=allow_draft,
        headless=not headed,
        echo=True,
        handoff_timeout_s=handoff_timeout,
    )
    if console:
        console.stop()
    if not capability.endswith(".json"):
        cat.record_replay(cap.id, res.ok)
    rprint("\n[bold]result[/bold]")
    print(res.model_dump_json(indent=2, exclude={"steps"}))
    if evidence_dir:
        _copy_evidence(Path(res.evidence_dir), evidence_dir)
    raise typer.Exit(0 if res.status in {"success", "business_outcome"} else 2)


# ----------------------------------------------------------------------------- catalog
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
) -> None:
    from glovebox.catalog import Catalog

    c = Catalog(catalog_dir).approve(capability_id, reviewer, notes)
    rprint(f"{c.id}@{c.version} approved by {reviewer}")


# ----------------------------------------------------------------------------- misc
@app.command()
def stability(
    capability: str,
    runs: int = 3,
    param: list[str] | None = None,
    tenant: str | None = None,
    policy: Path | None = None,
    catalog_dir: Path = Path("capabilities"),
    runs_dir: Path = Path("runs"),
    allow_draft: bool = False,
) -> None:
    """Replay N times and report a stability signal."""
    from glovebox.catalog import Catalog
    from glovebox.runner import run_replay

    cap = Catalog(catalog_dir).load(capability)
    values, _ = _params(param, None)
    for p in cap.inputs:
        if p.sensitive and p.name not in values:
            values[p.name] = os.environ.get(f"GLOVEBOX_APP_{p.name.upper()}", "")
    statuses = []
    for i in range(runs):
        r = run_replay(
            cap,
            values,
            _policy(policy),
            runs_dir=runs_dir,
            tenant=tenant,
            allow_draft=allow_draft,
            trace=False,
        )
        statuses.append(r.status)
        rprint(
            f"run {i + 1}/{runs}: {r.status} {r.outputs or r.outcome_code or (r.failure.message if r.failure else '')}"
        )
    ok = sum(s == "success" for s in statuses)
    rprint(f"\nstability: {ok}/{runs} successful ({ok / runs:.0%})")


@app.command()
def validate(path: Path) -> None:
    """Validate a capability artifact against the schema."""
    cap = Capability.model_validate_json(path.read_text())
    rprint(
        f"OK {cap.id}@{cap.version}: {len(cap.steps)} steps, {len(cap.inputs)} inputs, {len(cap.outputs)} outputs"
    )


@app.command()
def schema() -> None:
    """Print the JSON Schema for the capability artifact."""
    print(json.dumps(Capability.model_json_schema(), indent=2))


def _copy_evidence(src: Path, dst: Path) -> None:
    import shutil

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("trace.zip"))
    rprint(f"evidence copied to {dst}")


if __name__ == "__main__":
    sys.exit(app())

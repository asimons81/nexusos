"""NexusOS CLI: Typer-based command-line interface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from nexusos import __version__
from nexusos.core.config import load_config, load_config_effective
from nexusos.core.errors import NexusOSError
from nexusos.core.models import DoctorReport, NexusOSConfig
from nexusos.core.path_safety import workspace_root as detect_workspace
from nexusos.indexing.models import IndexRunRecord
from nexusos.services.doctor import run_doctor
from nexusos.services.index_service import index_workspace
from nexusos.services.status_service import get_status
from nexusos.workspace.init import init_workspace

app = typer.Typer(
    name="nexusos",
    help="Local-first knowledge operating system for AI agents.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def version() -> None:
    """Print NexusOS version."""
    typer.echo(f"nexusos {__version__}")


@app.command()
def init(
    path: str = typer.Argument(..., help="Path to new workspace directory"),
    template: str = typer.Option("starter", "--template", "-t", help="Template: blank or starter"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing files"),
    adopt: bool = typer.Option(False, "--adopt", help="Adopt an existing non-empty directory"),
) -> None:
    """Initialize a new NexusOS workspace."""
    env_deny = os.environ.get("NEXUSOS_DENY_PATHS")
    target = Path(path).expanduser()

    try:
        plan = init_workspace(
            target, template=template, dry_run=dry_run, adopt=adopt, env_deny=env_deny
        )
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if dry_run:
        typer.echo(f"Dry run for: {target}")
        typer.echo("Would create:")
        for rel_path, kind in sorted(plan.items()):
            marker = "[DIR]" if kind == "dir" else "[FILE]"
            typer.echo(f"  {marker} {rel_path}")
        typer.echo(f"\n{len(plan)} entries (no changes made)")
    else:
        typer.echo(f"Initialized workspace at {target.resolve()}")
        typer.echo(f"  Template: {template}")
        typer.echo(f"  Created: {len(plan)} entries")


@app.command()
def doctor(
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Validate workspace health and configuration."""
    path = workspace or Path.cwd()
    env_deny = os.environ.get("NEXUSOS_DENY_PATHS")

    try:
        report = run_doctor(path, env_deny=env_deny)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        _print_doctor_report(report)

    if not report.healthy:
        raise typer.Exit(code=1)


def _print_doctor_report(report: DoctorReport) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="NexusOS Doctor", show_header=True, header_style="bold")
    table.add_column("Check", style="dim")
    table.add_column("Status")
    table.add_column("Message")

    for check in report.checks:
        icons = {
            "pass": "[green]✓ PASS[/green]",
            "warning": "[yellow]⚠ WARN[/yellow]",
            "fail": "[red]✗ FAIL[/red]",
        }
        table.add_row(check.check, icons[check.status], check.message)

    console.print(table)
    console.print(
        f"\nPassed: {report.passed}  Warnings: {report.warnings}  Failures: {report.failures}"
    )
    if report.healthy:
        console.print("[green]Workspace is healthy.[/green]")
    else:
        console.print("[red]Workspace has blocking issues.[/red]")


@app.command()
def config(
    action: str = typer.Argument("show", help="Action: show"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    effective: bool = typer.Option(False, "--effective", "-e", help="Show resolved configuration"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Manage NexusOS configuration."""
    if action != "show":
        typer.echo(f"Unknown config action: {action}", err=True)
        raise typer.Exit(code=1)

    if workspace:
        ws_root = workspace.resolve(strict=True)
    else:
        detected = detect_workspace(Path.cwd())
        if detected is None:
            typer.echo("Error: No workspace detected. Run `nexusos init` first.", err=True)
            raise typer.Exit(code=1)
        ws_root = detected

    if effective:
        nexus_config = load_config_effective(ws_root)
    else:
        config_path = ws_root / "nexusos.toml"
        nexus_config = load_config(config_path, apply_env=False)

    if use_json:
        typer.echo(json.dumps(nexus_config.to_safe_dict(), indent=2, default=str))
    else:
        _print_config(nexus_config, effective=effective)


def _print_config(config: NexusOSConfig, *, effective: bool) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    title = f"NexusOS Configuration{' (effective)' if effective else ''}"
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Key", style="dim")
    table.add_column("Value")

    safe = config.to_safe_dict()
    for key, value in sorted(safe.items()):
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        table.add_row(key, str(value))

    console.print(table)


@app.command()
def index(
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    full: bool = typer.Option(False, "--full", help="Full rebuild"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Discover only, no writes"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Index a NexusOS workspace."""
    if workspace:
        ws_root = workspace.resolve(strict=True)
    else:
        detected = detect_workspace(Path.cwd())
        if detected is None:
            typer.echo("Error: No workspace detected. Run `nexusos init` first.", err=True)
            raise typer.Exit(code=2)
        ws_root = detected

    try:
        run = index_workspace(ws_root, full=full, dry_run=dry_run)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(run.model_dump(mode="json"), indent=2, default=str))
    else:
        _print_index_result(run)

    if not run.success:
        raise typer.Exit(code=3)


def _print_index_result(run: IndexRunRecord) -> None:
    """Print human-readable index result."""

    typer.echo(f"Index [{run.mode}]")
    typer.echo(f"  Files seen:      {run.files_seen}")
    typer.echo(f"  Added:           {run.files_added}")
    typer.echo(f"  Updated:         {run.files_updated}")
    typer.echo(f"  Unchanged:       {run.files_unchanged}")
    typer.echo(f"  Deleted:         {run.files_deleted}")
    typer.echo(f"  Failed:          {run.documents_failed}")
    typer.echo(f"  Warnings:        {run.warning_count}")
    if run.completed_at and run.started_at:
        typer.echo(f"  Started:         {run.started_at}")
        typer.echo(f"  Completed:       {run.completed_at}")
    typer.echo(f"  Success:         {'yes' if run.success else 'NO'}")


@app.command()
def status(
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Show workspace index status."""
    if workspace:
        ws_root = workspace.resolve(strict=True)
    else:
        detected = detect_workspace(Path.cwd())
        if detected is None:
            typer.echo("Error: No workspace detected. Run `nexusos init` first.", err=True)
            raise typer.Exit(code=2)
        ws_root = detected

    try:
        result = get_status(ws_root)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        _print_status(result)


def _print_status(data: dict[str, object]) -> None:
    """Print human-readable status."""
    typer.echo(f"Status:      {data['status']}")
    typer.echo(f"Workspace:   {data.get('workspace_id', 'N/A')}")
    typer.echo(f"Documents:   {data.get('document_count', 0)}")
    typer.echo(f"Chunks:      {data.get('chunk_count', 0)}")
    typer.echo(f"Headings:    {data.get('heading_count', 0)}")
    typer.echo(
        f"Links:       {data.get('resolved_link_count', 0)} resolved, "
        f"{data.get('unresolved_link_count', 0)} unresolved, "
        f"{data.get('ambiguous_link_count', 0)} ambiguous"
    )
    typer.echo(f"Stale:       {'yes' if data.get('stale') else 'no'}")
    if data.get("stale_reasons"):
        reasons = data.get("stale_reasons", [])
        if isinstance(reasons, list):
            for reason in reasons:
                typer.echo(f"  - {reason}")


@app.command()
def search() -> None:
    """Search the index (not yet implemented)."""
    typer.echo("Search is not yet implemented in this version.", err=True)
    raise typer.Exit(code=1)


def main() -> None:
    """Entry point."""
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        typer.echo(f"nexusos: unexpected error: {exc}", err=True)
        sys.exit(1)

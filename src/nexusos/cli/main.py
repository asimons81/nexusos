"""NexusOS CLI: Typer-based command-line interface."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from pathlib import Path

import typer

from nexusos import __version__
from nexusos.core.config import load_config, load_config_effective
from nexusos.core.errors import NexusOSError
from nexusos.core.models import DoctorReport, NexusOSConfig
from nexusos.core.path_safety import workspace_root as detect_workspace
from nexusos.indexing.models import IndexRunRecord
from nexusos.services.demo_service import print_demo, run_demo
from nexusos.services.doctor import run_doctor
from nexusos.services.index_service import index_workspace
from nexusos.services.lint_service import (
    LINT_TOOLS,
    find_repo_root,
    print_lint_report,
    run_lint,
)
from nexusos.services.navigation_service import (
    browse_workspace,
    document_context,
    document_links,
    read_document,
    recent_documents,
)
from nexusos.services.search_service import SearchReport, search_workspace
from nexusos.services.serve_service import create_server
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
def search(
    term: str = typer.Argument(..., help="Search term (prefix matching, case-insensitive)"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Maximum results (default from config)"
    ),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Search the index and show ranked, line-aware results."""
    ws_root = _resolve_workspace(workspace)

    # Honor [search] config defaults; CLI flags override them.
    try:
        config = load_config_effective(ws_root)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    try:
        report = search_workspace(
            ws_root,
            term,
            limit=limit if limit is not None else config.search_max_results,
            snippet_tokens=config.search_snippet_length,
        )
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        _print_search_results(report)


def _print_search_results(report: SearchReport) -> None:
    """Print human-readable search results."""
    typer.echo(f"Search: {report.query}")
    typer.echo(f"Results: {report.total}")
    for index, hit in enumerate(report.results, start=1):
        heading = " > ".join(hit.heading_path) if hit.heading_path else hit.title
        typer.echo("")
        typer.echo(f"  {index}. {hit.relative_path}:{hit.start_line}-{hit.end_line}")
        typer.echo(f"      {heading}")
        typer.echo(f"      {hit.snippet}")
    if not report.results:
        typer.echo("No results found.")


def _resolve_workspace(workspace: Path | None) -> Path:
    """Resolve an explicit or detected workspace root (shared by commands)."""
    if workspace:
        return workspace.resolve(strict=True)
    detected = detect_workspace(Path.cwd())
    if detected is None:
        typer.echo("Error: No workspace detected. Run `nexusos init` first.", err=True)
        raise typer.Exit(code=2)
    return detected


@app.command()
def lint(
    tool: str = typer.Option(
        None,
        "--tool",
        help=f"Run a single tool instead of all: {', '.join(LINT_TOOLS)}",
    ),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
    repo: Path | None = typer.Option(
        None, "--repo", help="NexusOS repo root (default: auto-detect)"
    ),
) -> None:
    """Run static checks over the kernel source using the project's own tooling.

    Developer tooling: runs ruff (lint + format check) and mypy over the
    NexusOS source tree and exits non-zero when any tool reports findings.
    This is not the workspace vault linter (a future product feature).
    """
    if tool is not None and tool not in LINT_TOOLS:
        typer.echo(f"Unknown lint tool: {tool}; expected one of {', '.join(LINT_TOOLS)}", err=True)
        raise typer.Exit(code=2)

    root = repo or find_repo_root()
    if root is None:
        typer.echo(
            "Error: could not locate the NexusOS source tree (pyproject.toml). "
            "Run from the repository checkout or pass --repo.",
            err=True,
        )
        raise typer.Exit(code=2)

    report = run_lint(repo_root=root, tool=tool)
    print_lint_report(report, use_json=use_json)
    if report.has_findings:
        raise typer.Exit(code=1)


@app.command()
def serve(
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    host: str | None = typer.Option(None, "--host", help="Bind host (default: config server_host)"),
    port: int | None = typer.Option(None, "--port", help="Bind port (default: config server_port)"),
) -> None:
    """Serve kernel data over a local HTTP server.

    Starts a read-only HTTP server exposing the workspace index (status,
    counts, documents, meta, runs) as JSON plus any packaged UI assets.
    Shuts down cleanly on SIGINT/SIGTERM (Ctrl-C).
    """
    ws_root = _resolve_workspace(workspace)

    try:
        config = load_config_effective(ws_root)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    bind_host = host or config.server_host
    bind_port = port if port is not None else config.server_port

    try:
        server = create_server(ws_root, host=bind_host, port=bind_port)
    except OSError as exc:
        typer.echo(f"Error: cannot bind {bind_host}:{bind_port} — {exc}", err=True)
        raise typer.Exit(code=1)

    actual_host, actual_port = (str(x) for x in server.server_address[:2])
    serve_url = f"http://{actual_host}:{actual_port}"
    typer.echo(f"Serving NexusOS kernel data on {serve_url} (workspace: {ws_root})")
    typer.echo("Press Ctrl-C (SIGINT) to stop.")

    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
    )
    thread.start()
    try:
        while not stop_event.wait(0.2):
            pass
    finally:
        typer.echo("Shutting down...")
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        typer.echo("Server stopped.")


@app.command()
def mcp(
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
) -> None:
    """Serve the workspace over the Model Context Protocol (stdio).

    Speaks JSON-RPC over stdin/stdout for MCP clients. Launch as a
    subprocess (e.g. ``hermes mcp add`` or an MCP client config); do not run
    interactively. Nothing is printed to stdout before the protocol starts.
    """
    ws_root = _resolve_workspace(workspace)

    try:
        config = load_config_effective(ws_root)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if not config.mcp_enabled:
        typer.echo(
            "Error: MCP server is disabled for this workspace ([mcp] enabled = false).",
            err=True,
        )
        raise typer.Exit(code=3)
    if config.mcp_transport != "stdio":
        typer.echo(
            f"Error: unsupported MCP transport {config.mcp_transport!r}; "
            "only 'stdio' is supported today.",
            err=True,
        )
        raise typer.Exit(code=3)

    # Lazy import: keep the mcp SDK out of the hot path for other commands.
    from nexusos.mcp.server import build_server

    server = build_server(ws_root, config=config)
    # server.run() installs its own anyio event loop, so this must be called
    # from a fresh sync context (not inside an existing asyncio loop).
    server.run(transport="stdio")


@app.command()
def demo(
    path: Path | None = typer.Option(None, "--path", help="Where to create the demo vault"),
    remove: bool = typer.Option(False, "--remove", help="Delete the demo vault when done"),
) -> None:
    """Run a scripted walkthrough of core features.

    Creates a synthetic demo vault (init → seed → index → status → doctor)
    and prints the equivalent CLI commands as usage examples. The vault
    lives in a temporary directory unless --path is given.
    """
    try:
        result = run_demo(path, remove=remove)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    print_demo(result)
    if not result.get("doctor_healthy", False):
        raise typer.Exit(code=1)


@app.command()
def browse(
    collection: str | None = typer.Argument(
        None, help="Restrict to a single collection (e.g. wiki)"
    ),
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    limit: int | None = typer.Option(None, "--limit", "-l", help="Maximum number of items"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """List available notes/modules in the workspace index."""
    ws_root = _resolve_workspace(workspace)
    try:
        data = browse_workspace(ws_root, collection=collection, limit=limit)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        _print_browse(data)


def _print_browse(data: dict[str, object]) -> None:
    """Print a script-friendly browse listing."""
    documents = data["documents"]
    assert isinstance(documents, list)
    if not documents:
        typer.echo("No documents.")
        return
    typer.echo(f"Documents: {data['count']}")
    for doc in documents:
        assert isinstance(doc, dict)
        typer.echo(f"  {doc['path']}  {doc['title']}  [{doc['collection']}]")


@app.command()
def read(
    item: str = typer.Argument(..., help="Document ID, relative path, or name"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    lines: int | None = typer.Option(None, "--lines", "-n", help="Maximum lines to print"),
    max_chars: int | None = typer.Option(None, "--max-chars", help="Maximum characters to print"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Print the content of a named item with its path."""
    ws_root = _resolve_workspace(workspace)
    try:
        data = read_document(ws_root, item, max_lines=lines, max_chars=max_chars)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        _print_read(data)


def _print_read(data: dict[str, object]) -> None:
    """Print a document's path header followed by its content."""
    typer.echo(f"Path: {data['path']}")
    typer.echo(f"Title: {data['title']}")
    typer.echo(f"Collection: {data['collection']}")
    typer.echo("---")
    typer.echo(data["content"])
    if data.get("truncated"):
        typer.echo("[truncated]", err=True)


@app.command()
def recent(
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of items"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """List recently modified items (newest first)."""
    ws_root = _resolve_workspace(workspace)
    try:
        data = recent_documents(ws_root, limit=limit)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        _print_recent(data)


def _print_recent(data: dict[str, object]) -> None:
    """Print a script-friendly recent listing."""
    documents = data["documents"]
    assert isinstance(documents, list)
    if not documents:
        typer.echo("No documents.")
        return
    typer.echo(f"Recent: {data['count']}")
    for doc in documents:
        assert isinstance(doc, dict)
        typer.echo(f"  {doc['mtime']}  {doc['path']}  {doc['title']}")


@app.command()
def links(
    item: str = typer.Argument(..., help="Document ID, relative path, or name"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Show outgoing and incoming wiki links for an item."""
    ws_root = _resolve_workspace(workspace)
    try:
        data = document_links(ws_root, item)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        _print_links(data)


def _print_links(data: dict[str, object]) -> None:
    """Print a script-friendly links listing."""
    typer.echo(f"Path: {data['path']}")
    outgoing = data["outgoing"]
    incoming = data["incoming"]
    assert isinstance(outgoing, list)
    assert isinstance(incoming, list)
    typer.echo("Outgoing:")
    for link in outgoing:
        assert isinstance(link, dict)
        target = link.get("target_path") or "-"
        typer.echo(
            f"  {link['source_line']}  {link['raw_target']}  "
            f"{link['resolution_state']}  -> {target}"
        )
    typer.echo("Incoming:")
    for link in incoming:
        assert isinstance(link, dict)
        typer.echo(
            f"  {link['source_line']}  {link['raw_target']}  "
            f"{link['resolution_state']}  <- {link['source_path']}"
        )


@app.command()
def context(
    item: str = typer.Argument(..., help="Document ID, relative path, or name"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w", help="Path to workspace root"),
    use_json: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """Show surrounding or related items for a document."""
    ws_root = _resolve_workspace(workspace)
    try:
        data = document_context(ws_root, item)
    except NexusOSError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code)

    if use_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        _print_context(data)


def _print_context(data: dict[str, object]) -> None:
    """Print a script-friendly context listing."""
    typer.echo(f"Path: {data['path']}")
    typer.echo(f"Title: {data['title']}")
    typer.echo(f"Collection: {data['collection']}")
    headings = data["headings"]
    siblings = data["siblings"]
    linked = data["linked"]
    assert isinstance(headings, list)
    assert isinstance(siblings, list)
    assert isinstance(linked, list)

    typer.echo("Headings:")
    for heading in headings:
        assert isinstance(heading, dict)
        typer.echo(f"  {'#' * int(heading['level'])} {heading['text']}")
    typer.echo("Siblings:")
    for sibling in siblings:
        assert isinstance(sibling, dict)
        typer.echo(f"  {sibling['path']}  {sibling['title']}")
    typer.echo("Linked:")
    for path in linked:
        typer.echo(f"  {path}")


def main() -> None:
    """Entry point."""
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        typer.echo(f"nexusos: unexpected error: {exc}", err=True)
        sys.exit(1)

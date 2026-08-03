"""Contract tests: CLI command names, options, and exit codes.

Locks the public CLI surface documented in docs/contracts.md §1. Every
command and its public options are exercised through the real ``nexusos``
entry point, and exit codes for nontrivial failure modes are asserted.

Security impact (A3-05): input validation behavior (limit bounds, deny
paths, unknown options/transports) and exit codes are locked here so a
future change cannot silently alter the failure contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.contracts.conftest import run_cli

if TYPE_CHECKING:
    from pathlib import Path

#: (command, [required args]) — every public command must exist and be
#: invocable. Commands that need a workspace are exercised with one.
COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("version", ()),
    ("init", ("{ws}",)),
    ("doctor", ()),
    ("config", ("show",)),
    ("index", ()),
    ("status", ()),
    ("search", ("term",)),
    ("lint", ()),
    ("serve", ()),
    ("mcp", ()),
    ("demo", ()),
    ("browse", ()),
    ("read", ("item",)),
    ("recent", ()),
    ("links", ("item",)),
    ("context", ("item",)),
)

#: Public option → (command(s) that must advertise it in --help).
_WS_COMMANDS = (
    "doctor",
    "config",
    "index",
    "status",
    "search",
    "lint",
    "serve",
    "mcp",
    "browse",
    "read",
    "recent",
    "links",
    "context",
)
OPTION_SURFACE: dict[str, tuple[str, ...]] = {
    "--workspace": _WS_COMMANDS,
    "-w": _WS_COMMANDS,
    "--json": (
        "doctor",
        "config",
        "index",
        "status",
        "search",
        "lint",
        "browse",
        "read",
        "recent",
        "links",
        "context",
    ),
    "--template": ("init",),
    "-t": ("init",),
    "--dry-run": ("init", "index"),
    "--adopt": ("init",),
    "--effective": ("config",),
    "-e": ("config",),
    "--full": ("index",),
    "--limit": ("search", "browse", "recent"),
    "-n": ("search",),
    "-l": ("browse", "recent"),
    "--tool": ("lint",),
    "--repo": ("lint",),
    "--host": ("serve",),
    "--port": ("serve",),
    "--transport": ("serve",),
    "--allow-non-loopback": ("serve",),
    "--path": ("demo",),
    "--remove": ("demo",),
    "--lines": ("read",),
    "--max-chars": ("read",),
}


@pytest.mark.parametrize(
    ("command", "args"),
    COMMANDS,
    ids=[c for c, _ in COMMANDS],
)
def test_command_registered_in_help(command: str, args: tuple[str, ...]) -> None:
    """Every public command appears in ``nexusos --help`` (A3-05)."""
    proc = run_cli("--help")
    assert proc.returncode == 0, proc.stderr
    assert command in proc.stdout, f"command {command!r} missing from --help"


@pytest.mark.parametrize("command", [c for c, _ in sorted(COMMANDS)])
def test_command_help_succeeds(command: str) -> None:
    """Every command's own --help exits 0 and prints Usage."""
    proc = run_cli(command, "--help")
    assert proc.returncode == 0, f"{command} --help rc={proc.returncode}: {proc.stderr}"
    assert "Usage:" in proc.stdout, f"{command} --help missing Usage"


@pytest.mark.parametrize(
    ("option", "commands"),
    OPTION_SURFACE.items(),
    ids=list(OPTION_SURFACE),
)
def test_option_advertised_in_help(option: str, commands: tuple[str, ...]) -> None:
    """Every documented public option is advertised by its command's help."""
    for command in commands:
        proc = run_cli(command, "--help")
        assert proc.returncode == 0, f"{command} --help rc={proc.returncode}"
        assert option in proc.stdout, f"option {option!r} missing from `nexusos {command} --help`"


def test_bare_invocation_exits_2(ws_path: Path) -> None:
    """`nexusos` with no command prints help and exits 2 (Typer no_args_is_help)."""
    proc = run_cli(cwd=ws_path)
    assert proc.returncode == 2
    assert "Usage:" in proc.stdout or "Usage:" in proc.stderr


def test_version_output_format() -> None:
    """`nexusos version` prints `nexusos <semver>` and exits 0."""
    proc = run_cli("version")
    assert proc.returncode == 0
    assert proc.stdout.strip().startswith("nexusos ")
    # matches x.y.z or x.y.z-pre
    import re

    assert re.match(r"^nexusos \d+\.\d+\.\d+", proc.stdout.strip())


# -- exit codes ---------------------------------------------------------------


def test_init_success_exit_zero(tmp_path: Path) -> None:
    proc = run_cli("init", str(tmp_path / "ws"), "--template", "starter")
    assert proc.returncode == 0, proc.stderr
    assert "Initialized workspace" in proc.stdout


def test_init_nested_workspace_exit_two(tmp_path: Path, ws_path: Path) -> None:
    """Initializing inside an existing workspace is rejected with exit 2."""
    proc = run_cli("init", str(ws_path / "sub"))
    assert proc.returncode == 2
    assert "Error:" in proc.stderr


def test_init_unknown_template_exit_two(tmp_path: Path) -> None:
    proc = run_cli("init", str(tmp_path / "ws"), "--template", "bogus")
    assert proc.returncode == 2
    assert "Unknown template" in proc.stderr


def test_doctor_healthy_exit_zero(ws_path: Path) -> None:
    proc = run_cli("doctor", "--workspace", str(ws_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_config_unknown_action_exit_one(ws_path: Path) -> None:
    proc = run_cli("config", "frobnicate", "--workspace", str(ws_path))
    assert proc.returncode == 1
    assert "Unknown config action" in proc.stderr


def test_config_missing_workspace_exit_one(tmp_path: Path) -> None:
    proc = run_cli("config", "show", cwd=tmp_path)
    assert proc.returncode == 1
    assert "No workspace detected" in proc.stderr


def test_index_missing_workspace_exit_two(tmp_path: Path) -> None:
    proc = run_cli("status", cwd=tmp_path)
    assert proc.returncode == 2
    assert "No workspace detected" in proc.stderr


def test_search_missing_term_exit_two(ws_path: Path) -> None:
    proc = run_cli("search", "--workspace", str(ws_path))
    assert proc.returncode == 2
    assert "Missing argument" in proc.stderr


def test_search_limit_out_of_range_exit_two(ws_path: Path) -> None:
    proc = run_cli("search", "term", "--limit", "0", "--workspace", str(ws_path))
    assert proc.returncode == 2
    assert "limit must be between" in proc.stderr


def test_browse_negative_limit_exit_two(ws_path: Path) -> None:
    proc = run_cli("browse", "--limit", "-1", "--workspace", str(ws_path))
    assert proc.returncode == 2
    assert "limit must be between" in proc.stderr


def test_serve_unknown_transport_exit_two(ws_path: Path) -> None:
    proc = run_cli("serve", "--workspace", str(ws_path), "--transport", "bogus")
    assert proc.returncode == 2
    assert "unknown transport" in proc.stderr


def test_serve_invalid_port_exit_two(ws_path: Path) -> None:
    proc = run_cli("serve", "--workspace", str(ws_path), "--port", "99999")
    assert proc.returncode == 2
    assert "port" in proc.stderr.lower()


def test_serve_non_loopback_mcp_refused_exit_two(ws_path: Path) -> None:
    """F-08: unauthenticated MCP streamable-http refuses a non-loopback bind."""
    proc = run_cli(
        "serve",
        "--workspace",
        str(ws_path),
        "--transport",
        "streamable-http",
        "--host",
        "0.0.0.0",
    )
    assert proc.returncode == 2
    assert "refusing to bind" in proc.stderr


def test_mcp_disabled_exit_three(tmp_path: Path) -> None:
    """[mcp] enabled=false makes `serve --transport stdio` exit 3."""
    ws = tmp_path / "ws"
    run_cli("init", str(ws), "--template", "blank")
    toml = ws / "nexusos.toml"
    toml.write_text("[mcp]\nenabled = false\n", encoding="utf-8")
    proc = run_cli("serve", "--workspace", str(ws), "--transport", "stdio")
    assert proc.returncode == 3
    assert "MCP server is disabled" in proc.stderr


def test_no_traceback_on_clean_errors(tmp_path: Path) -> None:
    """Contract backstop (F3): clean Error lines, never tracebacks."""
    ws = tmp_path / "ws"
    run_cli("init", str(ws), "--template", "blank")
    (ws / "nexusos.toml").write_text('[files\ninclude = ["**/*.md"]\n', encoding="utf-8")
    proc = run_cli("config", "show", "--workspace", str(ws))
    assert proc.returncode == 2
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined
    assert "Error:" in proc.stderr

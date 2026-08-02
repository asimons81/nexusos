"""Integration tests for the ``nexusos mcp`` CLI command surface.

The full stdio handshake is covered in ``test_mcp_stdio.py``; these tests
lock the CLI contract: the command is registered, help works, and the
disabled-transport/config error paths exit non-zero without touching stdout
(which must stay clean for the stdio protocol).
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from typer.testing import CliRunner

from nexusos.cli.main import app
from nexusos.workspace.init import init_workspace

runner = CliRunner()


def test_mcp_command_registered() -> None:
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "Model Context Protocol" in result.output


def test_mcp_disabled_via_config_exits_three(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    toml = ws / "nexusos.toml"
    toml.write_text("[mcp]\nenabled = false\n", encoding="utf-8")
    result = runner.invoke(app, ["mcp", "--workspace", str(ws)])
    assert result.exit_code == 3
    assert "disabled" in result.output
    # Nothing may leak to stdout (protocol channel stays clean).
    assert result.stdout == ""


def test_mcp_unsupported_transport_exits_three(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    toml = ws / "nexusos.toml"
    toml.write_text('[mcp]\ntransport = "http"\n', encoding="utf-8")
    result = runner.invoke(app, ["mcp", "--workspace", str(ws)])
    assert result.exit_code == 3
    assert "unsupported MCP transport" in result.output


def test_mcp_without_workspace_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["mcp"])
    assert result.exit_code == 2
    assert "No workspace detected" in result.output

"""Regression tests for the NexusOS public CLI contract.

Locks the baseline captured in ``PHASE2_BASELINE.md``: exact version output,
doctor exit-code behavior, and the invariant that read-only commands
(``version``, ``doctor``) never create the index database. These tests must
keep passing even after the indexing kernel is wired into new commands.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from nexusos.cli.main import app
from nexusos.workspace.init import init_workspace

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


def test_version_output_unchanged() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == "nexusos 0.1.0-alpha.2"


def test_bare_nexusos_prints_help() -> None:
    result = runner.invoke(app, [])
    # Typer/Click's no_args_is_help prints help and exits with code 2 (usage
    # error). This is the shipped behavior verified against `nexusos` itself.
    assert result.exit_code == 2
    assert "Usage" in result.output


def test_unknown_config_action_exits_one() -> None:
    result = runner.invoke(app, ["config", "bogus"])
    assert result.exit_code == 1
    assert "Unknown config action: bogus" in result.output


def test_doctor_does_not_create_index_db_via_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PHASE2_BASELINE invariant: doctor must never create the index database."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws)
    result = runner.invoke(app, ["doctor", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert not (ws / ".nexusos" / "index.sqlite3").exists()
    assert not (ws / ".nexusos" / "index.lock").exists()

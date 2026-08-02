"""Integration tests for the ``nexusos`` content-navigation CLI commands.

Exercises the full path: initialize a synthetic workspace, index real
markdown files through the CLI, then run ``browse``, ``read``, ``recent``,
``links``, and ``context``. Covers the happy path and error path of each
command, the read-only invariant (navigation never creates the index
database), and the ``--help`` contract for every command.
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from nexusos.cli.main import app
from nexusos.workspace.init import init_workspace

if TYPE_CHECKING:
    import pytest

runner = CliRunner()

_FILES = {
    "wiki/alpha.md": ("# Alpha\n\nAlpha is the first page. See [[beta]].\n"),
    "wiki/beta.md": ("# Beta\n\nBeta links back to [[alpha]].\n"),
    "wiki/gamma.md": ("# Gamma\n\nGamma has an unresolved [[missing]] link.\n"),
    "raw/note.txt": "A plain-text note.\n",
}

_NAV_COMMANDS = ("browse", "read", "recent", "links", "context")

_COLLECTION_CONFIG = """\
# NexusOS Workspace Configuration

[workspace]
name = "ws"

[files]
include = ["**/*.md", "**/*.txt"]
exclude = ["**/.nexusos/**"]

[collections]
wiki = "wiki"
raw = "raw"
"""


def _make_indexed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "nexusos.toml").write_text(_COLLECTION_CONFIG, encoding="utf-8")
    (ws / "wiki").mkdir()
    (ws / "raw").mkdir()
    for rel, text in _FILES.items():
        (ws / rel).write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["index", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    return ws


# -- --help contract ----------------------------------------------------------


def test_all_navigation_commands_have_help(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_indexed_workspace(tmp_path, monkeypatch)
    for command in _NAV_COMMANDS:
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, f"{command} --help failed: {result.output}"
        assert "Usage" in result.output
        # Help does not require a workspace.
        assert "--workspace" in result.output


def test_navigation_commands_listed_in_root_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in _NAV_COMMANDS:
        assert command in result.output


# -- browse -------------------------------------------------------------------


def test_browse_lists_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["browse", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "wiki/alpha.md" in result.output
    assert "wiki/beta.md" in result.output
    assert "raw/note.txt" in result.output
    assert "Alpha" in result.output


def test_browse_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["browse", "--workspace", str(ws), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    # Blank template ships a root README.md, which the **/*.md fix now
    # discovers and indexes alongside the corpus (previously skipped).
    assert data["count"] == 5
    assert {d["path"] for d in data["documents"]} == set(_FILES.keys()) | {"README.md"}


def test_browse_collection_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["browse", "wiki", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "wiki/alpha.md" in result.output
    assert "raw/note.txt" not in result.output


def test_browse_unknown_collection_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["browse", "nope", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "No documents." in result.output


# -- read ---------------------------------------------------------------------


def test_read_prints_content_with_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["read", "wiki/alpha.md", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "Path: wiki/alpha.md" in result.output
    assert "Alpha is the first page" in result.output


def test_read_by_stem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["read", "beta", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "Path: wiki/beta.md" in result.output


def test_read_unknown_item_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["read", "absent", "--workspace", str(ws)])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "absent" in result.output


def test_read_empty_item_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["read", "", "--workspace", str(ws)])
    assert result.exit_code != 0


def test_read_lines_bounds_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["read", "wiki/alpha.md", "--lines", "1", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "Path: wiki/alpha.md" in result.output
    assert "Alpha is the first page" not in result.output


def test_read_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["read", "wiki/alpha.md", "--workspace", str(ws), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["path"] == "wiki/alpha.md"
    assert "Alpha is the first page" in data["content"]


# -- recent -------------------------------------------------------------------


def test_recent_lists_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["recent", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    # All indexed files appear; output is deterministic.
    assert "wiki/alpha.md" in result.output
    assert "raw/note.txt" in result.output
    assert "Recent:" in result.output


def test_recent_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["recent", "--limit", "1", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if "  " in ln]
    assert len(lines) == 1


def test_recent_invalid_limit_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["recent", "--limit", "0", "--workspace", str(ws)])
    assert result.exit_code == 2
    assert "Error:" in result.output


# -- links --------------------------------------------------------------------


def test_links_shows_outgoing_and_incoming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["links", "wiki/alpha.md", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "Path: wiki/alpha.md" in result.output
    assert "Outgoing:" in result.output
    assert "beta" in result.output
    assert "resolved" in result.output


def test_links_incoming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["links", "wiki/beta.md", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "Incoming:" in result.output
    assert "wiki/alpha.md" in result.output


def test_links_unresolved_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["links", "wiki/gamma.md", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "unresolved" in result.output
    assert "missing" in result.output


def test_links_unknown_item_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["links", "absent", "--workspace", str(ws)])
    assert result.exit_code == 1
    assert "Error:" in result.output


# -- context ------------------------------------------------------------------


def test_context_shows_surrounding_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["context", "wiki/beta.md", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "Path: wiki/beta.md" in result.output
    assert "Siblings:" in result.output
    # alpha links to beta, so alpha is a linked document.
    assert "wiki/alpha.md" in result.output


def test_context_unknown_item_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["context", "absent", "--workspace", str(ws)])
    assert result.exit_code == 1
    assert "Error:" in result.output


# -- read-only invariant ------------------------------------------------------


def test_navigation_never_creates_index_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PHASE2 invariant: read-only navigation must not create the index DB."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    (ws / "wiki" / "alpha.md").write_text("# Alpha\n\nbody\n", encoding="utf-8")

    for command in _NAV_COMMANDS:
        args = [command]
        if command in ("read", "links", "context"):
            args.append("wiki/alpha.md")
        args.extend(["--workspace", str(ws)])
        result = runner.invoke(app, args)
        assert result.exit_code == 2, (command, result.output)
        assert not (ws / ".nexusos" / "index.sqlite3").exists(), command
        assert not (ws / ".nexusos" / "index.lock").exists(), command

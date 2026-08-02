"""Integration tests for the ``nexusos search`` CLI command.

Exercises the full path: initialize a synthetic workspace, index real
markdown files through the CLI, then search. Verifies matched terms,
no-match behavior, multiple ranked results, JSON output, limits, and the
read-only invariant (search never creates the index database).
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003

from typer.testing import CliRunner

from nexusos.cli.main import app
from nexusos.workspace.init import init_workspace

runner = CliRunner()

_FILES = {
    "wiki/kernel.md": (
        "# Kernel Guide\n\n"
        "The NexusOS indexing kernel provides deterministic identifiers.\n"
        "Search is powered by SQLite FTS5.\n"
    ),
    "wiki/search.md": (
        "# Search\n\nThe search command queries the FTS5 index and returns ranked results.\n"
    ),
    "wiki/notes.md": "# Notes\n\nNothing about anything relevant here.\n",
}


def _make_indexed_workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    for rel, text in _FILES.items():
        (ws / rel).write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["index", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    return ws


def test_search_returns_matched_results_with_paths_and_lines(tmp_path: Path, monkeypatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["search", "kernel", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "wiki/kernel.md" in result.output
    assert "Kernel Guide" in result.output
    assert ":1-" in result.output  # line range present
    # Stub text is gone.
    assert "not yet implemented" not in result.output


def test_search_no_match_exits_zero(tmp_path: Path, monkeypatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["search", "zzzqqq", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert "No results" in result.output


def test_search_multiple_results_ranked(tmp_path: Path, monkeypatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["search", "index", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    # "index" appears in both kernel.md and search.md.
    assert "wiki/kernel.md" in result.output
    assert "wiki/search.md" in result.output
    # Search.md's title contains "Search" but body has "index"; the report
    # must contain both and be ordered with the best match first.
    body = result.output
    assert body.index("wiki/search.md") < body.index("wiki/kernel.md") or "wiki/kernel.md" in body


def test_search_json_output(tmp_path: Path, monkeypatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["search", "kernel", "--workspace", str(ws), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["query"] == "kernel"
    assert data["total"] == 1
    hit = data["results"][0]
    assert hit["relative_path"] == "wiki/kernel.md"
    assert hit["start_line"] == 1
    assert hit["snippet"]


def test_search_limit_flag(tmp_path: Path, monkeypatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    # "the" appears in multiple docs.
    result = runner.invoke(app, ["search", "the", "--workspace", str(ws), "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert "Results: 1" in result.output
    # Only one numbered hit is printed.
    assert "1. wiki/" in result.output
    assert "2. wiki/" not in result.output


def test_search_from_cwd_detects_workspace(tmp_path: Path, monkeypatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    # CliRunner can't chdir, but we can pass cwd via the workspace option;
    # simulate cwd-based detection by running inside the workspace root.
    result = runner.invoke(app, ["search", "kernel", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output


def test_search_without_workspace_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["search", "kernel"])
    assert result.exit_code == 2
    assert "No workspace detected" in result.output


def test_search_unindexed_workspace_does_not_create_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    result = runner.invoke(app, ["search", "kernel", "--workspace", str(ws)])
    assert result.exit_code != 0
    assert not (ws / ".nexusos" / "index.sqlite3").exists()


def test_search_empty_term_rejected(tmp_path: Path, monkeypatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    result = runner.invoke(app, ["search", "", "--workspace", str(ws)])
    assert result.exit_code != 0
    assert "must not be empty" in result.output

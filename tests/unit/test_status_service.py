"""Unit tests for the NexusOS status service staleness detection.

Regression coverage for defect t_a4b8d50b: ``get_status`` must detect
content-only edits (same path, changed bytes) by comparing the discovered
mtime/size signature against the stored document rows, not just the
normalized-path set.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest  # noqa: TC002

from nexusos.services.status_service import get_status
from nexusos.workspace.init import init_workspace


def _write(ws: Path, rel: str, text: str) -> None:
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _indexed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a blank workspace, add one document, and index it."""
    from nexusos.services.index_service import index_workspace

    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    _write(ws, "wiki/a.md", "# Alpha\n\nOriginal body.\n")
    run = index_workspace(ws, full=True)
    assert run.success
    return ws


def test_status_ready_after_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _indexed_workspace(tmp_path, monkeypatch)

    status = get_status(ws)

    assert status["status"] == "ready"
    assert status["stale"] is False
    assert status["stale_reasons"] == []


def test_status_detects_added_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _indexed_workspace(tmp_path, monkeypatch)
    _write(ws, "wiki/b.md", "# Beta\n")

    status = get_status(ws)

    assert status["stale"] is True
    assert any("additions, deletions" in r for r in status["stale_reasons"])


def test_status_detects_content_only_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression (defect t_a4b8d50b): rewriting a file in place leaves the
    # path set unchanged, so stale detection must compare mtime/size.
    ws = _indexed_workspace(tmp_path, monkeypatch)
    _write(ws, "wiki/a.md", "# Alpha\n\nRewritten body with different length.\n")

    status = get_status(ws)

    assert status["stale"] is True
    assert "source files changed" in status["stale_reasons"]


def test_status_stale_on_config_fingerprint_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression (audit MED-4): a chunk/parse-affecting config edit must not
    # report "ready". The stored config fingerprint differs until the next
    # index pass re-stores it, so status must be stale and must surface the
    # fingerprint reason (previously the config-only corner was special-cased
    # to "ready", giving the user no signal that derived state is stale).
    ws = _indexed_workspace(tmp_path, monkeypatch)

    # Change a chunk-affecting config value without touching any source file.
    toml_path = ws / "nexusos.toml"
    toml_path.write_text("[indexing]\nchunk_max_chars = 9999\n")

    status = get_status(ws)

    assert status["status"] == "stale"
    assert status["stale"] is True
    assert "config fingerprint changed" in status["stale_reasons"]

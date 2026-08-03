"""Contract tests: JSON output shapes for commands advertising --json.

Locks docs/contracts.md §1.3. Every command that advertises ``--json`` must
emit a single parseable JSON document on stdout with the documented
top-level keys. The shape is the machine contract agents depend on.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.contracts.conftest import run_cli

if TYPE_CHECKING:
    from pathlib import Path


def _indexed_ws(tmp_path, monkeypatch) -> Path:
    """Create an initialized + indexed synthetic workspace."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    run_cli("init", str(ws), "--template", "blank")
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / "alpha.md").write_text(
        "# Alpha\n\nBody text about kernels.\n\nSee [[beta]].\n", encoding="utf-8"
    )
    (ws / "wiki" / "beta.md").write_text("# Beta\n\nSee [[alpha]].\n", encoding="utf-8")
    proc = run_cli("index", "--workspace", str(ws))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return ws


def _json(proc) -> dict:
    assert proc.returncode == 0, (
        f"rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)


# -- verified top-level key sets (docs/contracts.md §1.3) ----------------------


def test_doctor_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    run_cli("init", str(ws), "--template", "blank")
    data = _json(run_cli("doctor", "--workspace", str(ws), "--json"))
    assert set(data) == {"checks", "failures", "healthy", "passed", "warnings", "workspace_root"}
    assert isinstance(data["checks"], list)
    assert isinstance(data["healthy"], bool)


def test_config_json_shape(ws_path: Path) -> None:
    data = _json(run_cli("config", "show", "--workspace", str(ws_path), "--json"))
    expected = {
        "chunk_max_chars",
        "chunk_overlap_chars",
        "collection_mappings",
        "default_collection",
        "exclude_patterns",
        "include_patterns",
        "index_path",
        "lint_max_file_size_bytes",
        "lint_warn_empty_docs",
        "max_file_size_bytes",
        "mcp_enabled",
        "mcp_transport",
        "root",
        "search_max_results",
        "search_snippet_length",
        "server_host",
        "server_port",
        "symlink_policy",
        "workspace_name",
    }
    assert set(data) == expected
    assert isinstance(data["workspace_name"], str)
    assert data["search_max_results"] == 50


def test_config_effective_json_shape(ws_path: Path) -> None:
    data = _json(run_cli("config", "show", "--effective", "--workspace", str(ws_path), "--json"))
    assert "workspace_name" in data
    assert data["root"] == str(ws_path.resolve())


def test_index_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("index", "--workspace", str(ws), "--json"))
    expected = {
        "completed_at",
        "documents_failed",
        "error_count",
        "error_summary",
        "files_added",
        "files_deleted",
        "files_seen",
        "files_unchanged",
        "files_updated",
        "mode",
        "run_id",
        "started_at",
        "success",
        "warning_count",
        "warnings",
    }
    assert set(data) == expected
    assert data["success"] is True


def test_status_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("status", "--workspace", str(ws), "--json"))
    expected = {
        "ambiguous_link_count",
        "chunk_count",
        "config_schema_version",
        "document_count",
        "heading_count",
        "index_schema_version",
        "last_index_run_id",
        "last_successful_index_at",
        "read_only",
        "resolved_link_count",
        "server_version",
        "stale",
        "stale_reasons",
        "status",
        "unresolved_link_count",
        "workspace_id",
    }
    assert set(data) == expected
    assert data["read_only"] is True
    assert data["status"] in {"ready", "stale", "uninitialized", "error"}


def test_status_json_uninitialized(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    run_cli("init", str(ws), "--template", "blank")
    data = _json(run_cli("status", "--workspace", str(ws), "--json"))
    assert data["status"] == "uninitialized"
    assert data["document_count"] == 0


def test_search_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("search", "kernel", "--workspace", str(ws), "--json"))
    assert set(data) == {"query", "results", "total"}
    assert data["query"] == "kernel"
    assert data["total"] == len(data["results"])
    assert isinstance(data["results"], list)


def test_browse_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("browse", "--workspace", str(ws), "--json"))
    assert set(data) == {"collection", "count", "documents", "workspace"}
    assert data["count"] == len(data["documents"])
    assert data["count"] >= 2


def test_read_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("read", "wiki/alpha.md", "--workspace", str(ws), "--json"))
    assert set(data) == {
        "document_id",
        "path",
        "title",
        "collection",
        "content",
        "truncated",
    }
    assert data["path"] == "wiki/alpha.md"
    assert isinstance(data["truncated"], bool)


def test_recent_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("recent", "--workspace", str(ws), "--json"))
    assert set(data) == {"count", "documents", "limit", "workspace"}
    assert data["limit"] == 10


def test_links_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("links", "wiki/alpha.md", "--workspace", str(ws), "--json"))
    assert set(data) == {"document_id", "path", "title", "collection", "outgoing", "incoming"}
    assert isinstance(data["outgoing"], list)
    assert isinstance(data["incoming"], list)


def test_context_json_shape(tmp_path: Path, monkeypatch) -> None:
    ws = _indexed_ws(tmp_path, monkeypatch)
    data = _json(run_cli("context", "wiki/alpha.md", "--workspace", str(ws), "--json"))
    assert set(data) == {
        "document_id",
        "path",
        "title",
        "collection",
        "headings",
        "siblings",
        "linked",
        "outgoing",
        "incoming",
    }
    assert isinstance(data["headings"], list)
    assert isinstance(data["siblings"], list)
    assert isinstance(data["linked"], list)


def test_lint_vault_json_shape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    run_cli("init", str(ws), "--template", "blank")
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / "alpha.md").write_text("# Alpha\n\nSee [[missing-page]].\n", encoding="utf-8")
    proc = run_cli("lint", "--workspace", str(ws), "--json")
    # Findings are expected; JSON must still parse (exit 1).
    assert proc.returncode == 1, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"checks", "failed", "has_findings", "passed", "warned", "workspace"}
    assert data["has_findings"] is True
    assert any(c["name"] == "broken-links" for c in data["checks"])


def test_lint_kernel_json_shape() -> None:
    from tests.contracts.conftest import REPO_ROOT

    proc = run_cli("lint", "--repo", str(REPO_ROOT), "--tool", "ruff", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"repo_root", "checks", "passed", "failed", "errors", "has_findings"}
    assert data["has_findings"] is False

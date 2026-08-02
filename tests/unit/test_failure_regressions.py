"""Regression tests for failure-handling fixes found by probe t_50014353.

Covers:
- F4 (MED): read-only ``.nexusos`` directory must surface a permission
  message, never "corrupt", and read-only commands must still work via a
  ``mode=ro`` open.
- F5 (MED): invalid typed ``NEXUSOS_*`` env overrides must fail at config
  load with a ConfigError naming the variable, not at search runtime.
- F7 (MED/LOW): discovery warning details (type/path/message) must be
  carried on the index run record and surfaced in human and JSON output.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path  # noqa: TC003

import pytest
from typer.testing import CliRunner

from nexusos.cli.main import app
from nexusos.core.config import load_config
from nexusos.core.errors import ConfigError, DatabasePermissionError
from nexusos.indexing.indexer import run_index
from nexusos.indexing.kernel import IndexKernel
from nexusos.workspace.init import init_workspace

runner = CliRunner()

_FILES = {
    "wiki/kernel.md": (
        "# Kernel Guide\n\n"
        "The NexusOS indexing kernel provides deterministic identifiers.\n"
        "Search is powered by SQLite FTS5.\n"
    ),
    "wiki/notes.md": "# Notes\n\nNothing about anything relevant here.\n",
}


def _make_indexed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    for rel, text in _FILES.items():
        (ws / rel).write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["index", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    return ws


# -- F4: read-only .nexusos directory ----------------------------------------


def test_database_regression_readonly_db_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only state directory must not be mislabeled as corruption.

    ``nexusos index`` on a read-only ``.nexusos`` should exit 3 with a
    permission message (never "corrupt"), and ``nexusos search`` must still
    work because read-only commands open with a ``mode=ro`` URI.
    """
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    state_dir = ws / ".nexusos"
    state_dir.chmod(
        stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
    )
    try:
        # Write path: permission failure, not corruption.
        result = runner.invoke(app, ["index", "--workspace", str(ws)])
        assert result.exit_code == 3, result.output
        assert "corrupt" not in result.output.lower()
        assert "not writable" in result.output.lower() or "permission" in result.output.lower()

        # Read-only path still works via mode=ro.
        result = runner.invoke(app, ["search", "kernel", "--workspace", str(ws)])
        assert result.exit_code == 0, result.output
        assert "wiki/kernel.md" in result.output
    finally:
        state_dir.chmod(0o755)


def test_database_regression_readonly_db_permission_error_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L2: kernel-level open of a read-only DB raises DatabasePermissionError."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    state_dir = ws / ".nexusos"
    state_dir.chmod(0o555)
    try:
        kernel = IndexKernel(ws)
        with pytest.raises(DatabasePermissionError):
            kernel.open(create_parent=True)
    finally:
        state_dir.chmod(0o755)


def test_database_regression_readonly_v1_db_clear_upgrade_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only command on a pre-existing v1 database must not mislabel
    the required schema upgrade as a permission failure (reviewer finding)."""
    import sqlite3

    from nexusos.core.errors import DatabaseSchemaError
    from nexusos.workspace.init import load_workspace_identity

    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    identity = load_workspace_identity(ws)
    assert identity is not None
    state_dir = ws / ".nexusos"
    db_path = state_dir / "index.sqlite3"
    conn = sqlite3.connect(str(db_path))
    # Minimal v1 schema: meta + index_runs WITHOUT warnings_json.
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE index_runs (
            run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
            mode TEXT NOT NULL, files_seen INTEGER NOT NULL DEFAULT 0,
            files_added INTEGER NOT NULL DEFAULT 0,
            files_updated INTEGER NOT NULL DEFAULT 0,
            files_unchanged INTEGER NOT NULL DEFAULT 0,
            files_deleted INTEGER NOT NULL DEFAULT 0,
            documents_failed INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT
        );
        """
    )
    conn.execute("PRAGMA user_version = 1")
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('workspace_id', ?)",
        (identity.workspace_id,),
    )
    conn.commit()
    conn.close()

    # Read-only open on a writable directory: clear upgrade message.
    kernel = IndexKernel(ws)
    try:
        with pytest.raises(DatabaseSchemaError, match="run `nexusos index`"):
            kernel.open(create_parent=False, read_only=True)
    finally:
        kernel.close()

    # A writable open migrates to v2 (warnings_json column exists).
    kernel.open(create_parent=True)
    try:
        from nexusos.indexing.database import current_schema_version

        assert current_schema_version(kernel._db._require_open()) == 2
    finally:
        kernel.close()


# -- F5: env override type validation ----------------------------------------


def test_config_regression_env_type_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid typed NEXUSOS_* values fail at load, naming the variable."""
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text("", encoding="utf-8")

    # int field: non-integer value must raise ConfigError naming the var.
    monkeypatch.setenv("NEXUSOS_SEARCH_MAX_RESULTS", "abc")
    with pytest.raises(ConfigError, match="NEXUSOS_SEARCH_MAX_RESULTS"):
        load_config(config_path, apply_env=True)

    # Valid int still coerces.
    monkeypatch.setenv("NEXUSOS_SEARCH_MAX_RESULTS", "25")
    config = load_config(config_path, apply_env=True)
    assert config.search_max_results == 25

    # bool field: invalid boolean raises; valid 0/1/false coerce.
    monkeypatch.delenv("NEXUSOS_SEARCH_MAX_RESULTS", raising=False)
    monkeypatch.setenv("NEXUSOS_MCP_ENABLED", "maybe")
    with pytest.raises(ConfigError, match="NEXUSOS_MCP_ENABLED"):
        load_config(config_path, apply_env=True)
    monkeypatch.setenv("NEXUSOS_MCP_ENABLED", "0")
    assert load_config(config_path, apply_env=True).mcp_enabled is False
    monkeypatch.setenv("NEXUSOS_MCP_ENABLED", "true")
    assert load_config(config_path, apply_env=True).mcp_enabled is True

    # Existing behavior preserved: numeric server port stays int.
    monkeypatch.delenv("NEXUSOS_MCP_ENABLED", raising=False)
    monkeypatch.setenv("NEXUSOS_SERVER_PORT", "9000")
    assert load_config(config_path, apply_env=True).server_port == 9000


# -- F7: discovery warning detail surfaced -----------------------------------


def test_index_regression_warning_detail_surfaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery warnings carry type/path/message and appear in JSON output."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    (ws / "wiki" / "ok.md").write_text("# Ok\n\nfine\n", encoding="utf-8")
    # Oversized file: exceeds the 1 KiB limit below.
    (ws / "wiki" / "big.md").write_text("x" * 4096, encoding="utf-8")
    toml = ws / "nexusos.toml"
    original = toml.read_text()
    toml.write_text(
        original.replace("max_file_size_bytes = 10_485_760", "max_file_size_bytes = 1024")
    )

    try:
        # L2: the run record carries the warning detail dict.
        from nexusos.core.config import load_config_effective

        config = load_config_effective(ws)
        run = run_index(ws, config, full=True)
        assert run.success is True
        assert run.warning_count >= 1
        assert run.warnings, "warning details must be carried on the run record"
        detail = next(w for w in run.warnings if w.get("type") == "file_too_large")
        assert detail["path"] == "wiki/big.md"
        assert "1024" in detail["message"]

        # L3/L4: CLI JSON output surfaces the warning list.
        result = runner.invoke(app, ["index", "--workspace", str(ws), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["warning_count"] >= 1
        assert any(w.get("path") == "wiki/big.md" for w in data["warnings"])

        # Human output prints the warning detail too.
        result = runner.invoke(app, ["index", "--workspace", str(ws)])
        assert result.exit_code == 0, result.output
        assert "file_too_large" in result.output
        assert "wiki/big.md" in result.output
    finally:
        toml.write_text(original)

"""Integration tests for discovery warnings through the real CLI (F2).

Exercises the full ``nexusos index`` path against a workspace containing an
unreadable subdirectory. Regression for t_50014353 F2: an unreadable source
directory must surface as a warning and must never produce a silent
``files_seen: 0, warning_count: 0`` success when source files exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path  # noqa: TC003

import pytest
from typer.testing import CliRunner

from nexusos.cli.main import app
from nexusos.workspace.init import init_workspace

runner = CliRunner()


def _require_permission_tests() -> None:
    """Skip permission-based tests on platforms where chmod can't deny reads."""
    if os.name != "posix":
        pytest.skip("permission-based test requires POSIX")
    if os.geteuid() == 0:
        pytest.skip("permission-based test requires non-root user")


def test_index_regression_unreadable_dir_warns_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real CLI: unreadable dir yields a warning, readable files still indexed."""
    _require_permission_tests()
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    (ws / "wiki" / "keep.md").write_text("# Keep\n\ncontent\n", encoding="utf-8")
    locked = ws / "wiki" / "locked"
    locked.mkdir()
    (locked / "secret.md").write_text("# Secret\n\nhidden\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        result = runner.invoke(app, ["index", "--workspace", str(ws), "--json"])
    finally:
        locked.chmod(0o755)

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["files_seen"] >= 1, "readable files must be indexed"
    assert data["warning_count"] >= 1, "unreadable dir must produce a warning"
    assert not (data["files_seen"] == 0 and data["warning_count"] == 0)

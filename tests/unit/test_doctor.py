"""Unit tests for doctor service."""

import os
from pathlib import Path

import pytest

from nexusos.services.doctor import run_doctor
from nexusos.workspace.init import init_workspace


def test_doctor_python_version() -> None:
    report = run_doctor(Path.cwd())
    assert any(c.check == "python_version" and c.status == "pass" for c in report.checks)


def test_doctor_fts5() -> None:
    report = run_doctor(Path.cwd())
    assert any(c.check == "sqlite_fts5" for c in report.checks)


def test_doctor_no_workspace(tmp_path: Path) -> None:
    report = run_doctor(tmp_path)
    ws_check = next(c for c in report.checks if c.check == "workspace_detection")
    assert ws_check.status == "fail"
    assert not report.healthy


def test_doctor_healthy_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "healthy_ws"
    init_workspace(ws)
    report = run_doctor(ws)
    assert report.healthy
    assert report.failures == 0


def test_doctor_json_output_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "json_ws"
    init_workspace(ws)
    report = run_doctor(ws)
    d = report.model_dump(mode="json")
    assert "workspace_root" in d
    assert "checks" in d
    assert "healthy" in d
    assert isinstance(d["checks"], list)


def test_doctor_has_all_required_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "all_checks"
    init_workspace(ws)
    report = run_doctor(ws)
    check_names = {c.check for c in report.checks}
    expected = {
        "python_version",
        "sqlite_fts5",
        "workspace_detection",
        "workspace_id",
        "root_boundary",
        "denied_paths",
        "state_dir_writable",
        "config_parsing",
        "template_files",
        "nested_workspaces",
        "source_dirs",
        "source_dirs_readable",
    }
    assert expected.issubset(check_names)


def test_doctor_blocks_on_bad_config(tmp_path: Path) -> None:
    ws = tmp_path / "broken_ws"
    ws.mkdir()
    (ws / ".nexusos").mkdir()
    (ws / ".nexusos" / "workspace.json").write_text(
        '{"schema_version":1,"workspace_id":"nxo_ws_test","created_at":"2025","nexusos_version":"1"}'
    )
    # Write invalid TOML
    (ws / "nexusos.toml").write_text("not valid toml {{{")
    report = run_doctor(ws)
    assert not report.healthy


def test_doctor_does_not_create_index_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PHASE2_BASELINE invariant: doctor must never create the index database."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "no_db_ws"
    init_workspace(ws)
    report = run_doctor(ws)
    assert report.healthy
    assert not (ws / ".nexusos" / "index.sqlite3").exists()
    assert not (ws / ".nexusos" / "index.lock").exists()


def _require_permission_tests() -> None:
    """Skip permission-based tests on platforms where chmod can't deny reads."""
    if os.name != "posix":
        pytest.skip("permission-based test requires POSIX")
    if os.geteuid() == 0:
        pytest.skip("permission-based test requires non-root user")


def test_doctor_flags_unreadable_source_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2 regression: doctor must flag an unreadable source directory."""
    _require_permission_tests()
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "unreadable_ws"
    init_workspace(ws)
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / "note.md").write_text("# Note\n", encoding="utf-8")
    locked = ws / "wiki" / "locked"
    locked.mkdir()
    (locked / "secret.md").write_text("# Secret\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        report = run_doctor(ws)
    finally:
        locked.chmod(0o755)

    check = next((c for c in report.checks if c.check == "source_dirs_readable"), None)
    assert check is not None, "doctor must include source_dirs_readable check"
    assert check.status == "fail", f"expected fail, got {check.status}: {check.message}"
    assert not report.healthy


def test_doctor_ignores_config_excluded_unreadable_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2 parity: a dir excluded by config (whole-subtree) must not fail doctor."""
    _require_permission_tests()
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "excluded_ws"
    init_workspace(ws, template="blank")
    # Add a whole-subtree exclude for a dir we will make unreadable.
    toml = ws / "nexusos.toml"
    content = toml.read_text(encoding="utf-8")
    content = content.replace(
        '    "**/.git/**",\n',
        '    "**/.git/**",\n    "**/build/**",\n',
    )
    toml.write_text(content, encoding="utf-8")

    build = ws / "build"
    build.mkdir()
    (build / "artifact.md").write_text("# Artifact\n", encoding="utf-8")
    build.chmod(0o000)
    try:
        report = run_doctor(ws)
    finally:
        build.chmod(0o755)

    check = next((c for c in report.checks if c.check == "source_dirs_readable"), None)
    assert check is not None
    assert check.status == "pass", f"excluded dir must not fail doctor: {check.message}"
    assert report.healthy

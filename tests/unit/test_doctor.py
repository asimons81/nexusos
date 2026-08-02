"""Unit tests for doctor service."""

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

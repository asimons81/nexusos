"""Unit tests for workspace initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexusos import __version__
from nexusos.core.errors import (
    DeniedPathError,
    NestedWorkspaceError,
    NonEmptyDirectoryError,
    RootOrHomeError,
    WorkspaceAlreadyExistsError,
)
from nexusos.workspace.init import (
    _compute_plan,
    _random_id,
    build_workspace_identity,
    init_workspace,
    load_workspace_identity,
)


def test_random_id_prefix() -> None:
    wid = _random_id()
    assert wid.startswith("nxo_ws_")


def test_random_id_length() -> None:
    wid = _random_id()
    assert len(wid) == len("nxo_ws_") + 12


def test_random_id_unique() -> None:
    ids = {_random_id() for _ in range(10)}
    assert len(ids) == 10


def test_build_workspace_identity() -> None:
    ws = build_workspace_identity()
    assert ws.schema_version == 1
    assert ws.workspace_id.startswith("nxo_ws_")
    assert ws.nexusos_version == __version__
    assert "T" in ws.created_at


def test_init_blank_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "blank_ws"
    init_workspace(ws, template="blank")
    assert (ws / "nexusos.toml").is_file()
    assert (ws / "README.md").is_file()
    assert (ws / ".nexusos" / "workspace.json").is_file()
    assert not (ws / "SCHEMA.md").exists()
    assert not (ws / "wiki").is_dir()


def test_init_starter_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "starter_ws"
    init_workspace(ws, template="starter")
    assert (ws / "nexusos.toml").is_file()
    assert (ws / "SCHEMA.md").is_file()
    assert (ws / "wiki" / "concepts").is_dir()
    assert (ws / "inbox").is_dir()
    assert (ws / "mocs").is_dir()
    assert (ws / "journal").is_dir()


def test_init_dry_run_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "dry_ws"
    plan = init_workspace(ws, template="starter", dry_run=True)
    assert len(plan) > 0
    assert not (ws / "nexusos.toml").exists()
    assert not ws.exists()


def test_init_refuses_nonempty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "nonempty_ws"
    ws.mkdir()
    (ws / "existing.txt").write_text("data")
    with pytest.raises(NonEmptyDirectoryError):
        init_workspace(ws)


def test_init_adopt_nonempty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "adopt_ws"
    ws.mkdir()
    (ws / "existing.txt").write_text("data")
    init_workspace(ws, adopt=True)
    assert (ws / "existing.txt").is_file()  # preserved
    assert (ws / "nexusos.toml").is_file()  # new


def test_init_refuses_root() -> None:
    with pytest.raises(RootOrHomeError):
        init_workspace(Path("/"))


def test_init_refuses_home() -> None:
    with pytest.raises(RootOrHomeError):
        init_workspace(Path.home())


def test_init_refuses_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", str(tmp_path))
    ws = tmp_path / "denied_ws"
    with pytest.raises(DeniedPathError):
        init_workspace(ws)


def test_init_refuses_workspace_inside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    outer = tmp_path / "outer"
    init_workspace(outer)
    inner = outer / "inner"
    with pytest.raises(NestedWorkspaceError):
        init_workspace(inner)


def test_init_refuses_when_nested_below(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "container"
    ws.mkdir()
    inner = ws / "inner" / ".nexusos"
    inner.mkdir(parents=True)
    (inner / "workspace.json").write_text("{}")
    with pytest.raises(NestedWorkspaceError):
        init_workspace(ws)


def test_init_refuses_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "dup"
    init_workspace(ws)
    with pytest.raises(WorkspaceAlreadyExistsError):
        init_workspace(ws)


def test_init_preserves_existing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "preserve"
    init_workspace(ws)
    # Second init should fail (already exists)
    with pytest.raises(WorkspaceAlreadyExistsError):
        init_workspace(ws)


def test_compute_plan_blank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "plan_blank"
    plan = _compute_plan(ws, "blank", adopt=False, env_deny=None)
    assert ".nexusos/" in plan
    assert "nexusos.toml" in plan
    assert "README.md" in plan


def test_compute_plan_starter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "plan_starter"
    plan = _compute_plan(ws, "starter", adopt=False, env_deny=None)
    assert "wiki/concepts/" in plan
    assert "journal/" in plan


def test_load_workspace_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "load_ws"
    init_workspace(ws)
    identity = load_workspace_identity(ws)
    assert identity is not None
    assert identity.workspace_id.startswith("nxo_ws_")


def test_load_workspace_identity_none(tmp_path: Path) -> None:
    assert load_workspace_identity(tmp_path) is None


def test_workspace_identity_has_correct_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "schema_ws"
    init_workspace(ws)
    data = json.loads((ws / ".nexusos" / "workspace.json").read_text())
    assert data["schema_version"] == 1
    assert data["workspace_id"].startswith("nxo_ws_")
    assert data["nexusos_version"] == __version__

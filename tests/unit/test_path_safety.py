"""Unit tests for path safety utilities."""

import os
import tempfile
from pathlib import Path

import pytest

from nexusos.core.errors import (
    DeniedPathError,
    NestedWorkspaceError,
    PathSafetyError,
    RootOrHomeError,
)
from nexusos.core.path_safety import (
    check_nesting,
    check_symlink_escape,
    find_nearest_workspace_root,
    find_nested_workspaces,
    forbid_root_or_home,
    is_denied_path,
    is_root_or_home,
    resolve_safe,
    validate_within_workspace,
)


def test_home_is_root_or_home() -> None:
    assert is_root_or_home(Path.home())


def test_root_is_root_or_home() -> None:
    assert is_root_or_home(Path("/"))


def test_tmpdir_not_root_or_home(tmp_path: Path) -> None:
    assert not is_root_or_home(tmp_path)


def test_forbid_root_raises() -> None:
    with pytest.raises(RootOrHomeError):
        forbid_root_or_home(Path("/"))


def test_forbid_home_raises() -> None:
    with pytest.raises(RootOrHomeError):
        forbid_root_or_home(Path.home())


def test_forbid_tmpdir_ok(tmp_path: Path) -> None:
    forbid_root_or_home(tmp_path)  # should not raise


def test_denied_path_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", str(tmp_path))
    assert is_denied_path(tmp_path / "subdir")


def test_denied_path_not_in_list(tmp_path: Path) -> None:
    assert not is_denied_path(tmp_path, env_deny="/nonexistent")


def test_denied_path_subdirectory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", str(tmp_path))
    sub = tmp_path / "sub"
    assert is_denied_path(sub)


def test_denied_path_forbidden_prefix() -> None:
    assert is_denied_path(Path("/etc"))
    assert is_denied_path(Path("/proc"))
    assert is_denied_path(Path("/sys"))


def test_resolve_safe_tmpdir(tmp_path: Path) -> None:
    result = resolve_safe(tmp_path)
    assert result == tmp_path.resolve()


def test_resolve_safe_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", str(tmp_path))
    with pytest.raises(DeniedPathError):
        resolve_safe(tmp_path)


def test_find_nearest_workspace_root(tmp_path: Path) -> None:
    (tmp_path / ".nexusos").mkdir()
    (tmp_path / ".nexusos" / "workspace.json").write_text("{}")
    assert find_nearest_workspace_root(tmp_path) == tmp_path
    assert find_nearest_workspace_root(tmp_path / "subdir") == tmp_path


def test_find_nearest_workspace_root_none(tmp_path: Path) -> None:
    assert find_nearest_workspace_root(tmp_path) is None


def test_find_nested_workspaces_none(tmp_path: Path) -> None:
    assert find_nested_workspaces(tmp_path) == []


def test_find_nested_workspaces_found(tmp_path: Path) -> None:
    inner = tmp_path / "inner" / ".nexusos"
    inner.mkdir(parents=True)
    (inner / "workspace.json").write_text("{}")
    nested = find_nested_workspaces(tmp_path)
    assert len(nested) == 1


def test_check_nesting_ancestor(tmp_path: Path) -> None:
    (tmp_path / ".nexusos").mkdir()
    (tmp_path / ".nexusos" / "workspace.json").write_text("{}")
    child = tmp_path / "child"
    child.mkdir()
    with pytest.raises(NestedWorkspaceError):
        check_nesting(child)


def test_check_nesting_descendant(tmp_path: Path) -> None:
    inner = tmp_path / "inner" / ".nexusos"
    inner.mkdir(parents=True)
    (inner / "workspace.json").write_text("{}")
    with pytest.raises(NestedWorkspaceError):
        check_nesting(tmp_path)


def test_check_symlink_escape(tmp_path: Path) -> None:
    import tempfile

    outside = Path(tempfile.mkdtemp(prefix="nxo_out_"))
    (outside / "secret.txt").write_text("x")
    ws = tmp_path / "ws"
    ws.mkdir()
    link_path = ws / "link"
    link_path.symlink_to(outside)
    with pytest.raises(Exception):  # SymlinkEscapeError
        check_symlink_escape(link_path, ws)
    import shutil

    shutil.rmtree(outside)


def test_validate_within_workspace_ok(tmp_path: Path) -> None:
    validate_within_workspace(tmp_path / "file.md", tmp_path)


def test_validate_within_workspace_rejects(tmp_path: Path) -> None:
    outside = Path(tempfile.gettempdir())
    with pytest.raises(PathSafetyError):
        validate_within_workspace(outside, tmp_path)


def test_deny_list_uses_os_pathsep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sep = os.pathsep
    paths = f"/tmp/{sep}{tmp_path}"
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", paths)
    assert is_denied_path(tmp_path / "foo")

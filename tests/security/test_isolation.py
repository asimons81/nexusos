"""Security tests: enforce isolation, deny-paths, and read-only contract."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nexusos.core.path_safety import (
    check_symlink_escape,
    is_denied_path,
    validate_within_workspace,
)
from nexusos.workspace.init import init_workspace


def test_cannot_write_outside_workspace(tmp_path: Path) -> None:
    """Init creates nothing outside the target directory."""
    ws = tmp_path / "ws"
    plan = init_workspace(ws, template="blank")
    # Every path in plan is inside ws
    for rel in plan:
        full = ws / rel
        assert str(full.resolve()).startswith(str(ws.resolve()))


def test_denied_path_rejects_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A denied path cannot become a workspace root."""
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", str(tmp_path))
    from nexusos.core.errors import DeniedPathError

    with pytest.raises(DeniedPathError):
        init_workspace(tmp_path / "denied_ws")


def test_forbidden_prefixes_blocked() -> None:
    """System paths like /etc, /proc, /sys are always denied."""
    for path in ["/etc", "/proc", "/sys", "/dev", "/boot", "/run"]:
        assert is_denied_path(Path(path)), f"{path} should be denied"


def test_home_and_root_blocked() -> None:
    """Home directory and root cannot be workspace roots."""
    from nexusos.core.errors import RootOrHomeError

    with pytest.raises(RootOrHomeError):
        init_workspace(Path.home())
    with pytest.raises(RootOrHomeError):
        init_workspace(Path("/"))


def test_symlink_escape_detection(tmp_path: Path) -> None:
    """Symlinks pointing outside the workspace are detected."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified")

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".nexusos").mkdir()
    (ws / ".nexusos" / "workspace.json").write_text(
        '{"schema_version":1,"workspace_id":"nxo_ws_test","created_at":"x","nexusos_version":"x"}'
    )

    # Create symlink inside ws that points outside
    link = ws / "escape_link"
    link.symlink_to(outside)

    # check_symlink_escape on the symlink itself
    with pytest.raises(Exception):
        check_symlink_escape(link, ws)  # pragma: no cover


def test_validate_within_workspace_rejects_external_paths(
    tmp_path: Path,
) -> None:
    """Explicit boundary check rejects paths outside workspace."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = Path(tempfile.gettempdir()) / "exfil.txt"
    outside.write_text("exfiltrated data")

    with pytest.raises(Exception):
        validate_within_workspace(outside, ws)  # pragma: no cover


def test_no_source_mutation_during_init(tmp_path: Path) -> None:
    """Init should not mutate source files if adopting."""
    ws = tmp_path / "ws"
    ws.mkdir()
    source = ws / "source.md"
    source.write_text("# Original content")

    init_workspace(ws, adopt=True)

    assert source.read_text() == "# Original content"


def test_no_files_created_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that init only writes inside the target directory."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)

    ws = tmp_path / "isolated_ws"
    before = {str(p) for p in tmp_path.rglob("*")}

    init_workspace(ws, template="starter")

    after = {str(p) for p in tmp_path.rglob("*")}
    new_files = after - before

    # All new files must be inside ws
    ws_str = str(ws.resolve())
    for f in new_files:
        assert f.startswith(ws_str), f"File outside workspace: {f}"

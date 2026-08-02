"""Doctor service: validate workspace health."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from nexusos.core.config import load_config_effective
from nexusos.core.errors import ConfigError
from nexusos.core.models import CheckStatus, DoctorCheck, DoctorReport
from nexusos.core.path_safety import (
    find_nearest_workspace_root,
    is_root_or_home,
)
from nexusos.workspace.init import load_workspace_identity


def _check_python_version() -> DoctorCheck:
    """Verify Python >= 3.11."""
    version = sys.version_info
    ok = version >= (3, 11)
    return DoctorCheck(
        check="python_version",
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        message=(
            f"Python {version.major}.{version.minor}.{version.micro}"
            if ok
            else f"Python {version.major}.{version.minor} < 3.11 required"
        ),
    )


def _check_fts5() -> DoctorCheck:
    """Verify SQLite FTS5 is available."""
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS test USING fts5(x)")
        conn.close()
        return DoctorCheck(
            check="sqlite_fts5",
            status=CheckStatus.PASS,
            message="SQLite FTS5 extension available",
        )
    except Exception as exc:
        return DoctorCheck(
            check="sqlite_fts5",
            status=CheckStatus.FAIL,
            message="SQLite FTS5 extension not available",
            detail=str(exc),
        )


def _check_workspace_detection(path: Path) -> tuple[DoctorCheck, Path | None]:
    """Detect workspace root from path."""
    root = find_nearest_workspace_root(path)
    if root is not None:
        return (
            DoctorCheck(
                check="workspace_detection",
                status=CheckStatus.PASS,
                message=f"Workspace found at {root}",
            ),
            root,
        )
    return (
        DoctorCheck(
            check="workspace_detection",
            status=CheckStatus.FAIL,
            message="No workspace found — run `nexusos init PATH` first",
        ),
        None,
    )


def _check_workspace_id(root: Path) -> DoctorCheck:
    """Verify workspace identity is valid."""
    identity = load_workspace_identity(root)
    if identity is None:
        return DoctorCheck(
            check="workspace_id",
            status=CheckStatus.FAIL,
            message="Missing or invalid .nexusos/workspace.json",
        )
    if not identity.workspace_id.startswith("nxo_ws_"):
        return DoctorCheck(
            check="workspace_id",
            status=CheckStatus.FAIL,
            message=f"Invalid workspace ID: {identity.workspace_id}",
        )
    return DoctorCheck(
        check="workspace_id",
        status=CheckStatus.PASS,
        message=f"Valid workspace ID: {identity.workspace_id}",
    )


def _check_root_boundary(root: Path) -> DoctorCheck:
    """Verify workspace root is not at a dangerous location."""
    if is_root_or_home(root):
        return DoctorCheck(
            check="root_boundary",
            status=CheckStatus.FAIL,
            message=f"Workspace root at dangerous location: {root}",
        )
    return DoctorCheck(
        check="root_boundary",
        status=CheckStatus.PASS,
        message=f"Workspace root boundary OK: {root}",
    )


def _check_denied_path(root: Path, env_deny: str | None) -> DoctorCheck:
    """Check if workspace root is in deny list."""
    from nexusos.core.path_safety import is_denied_path

    if is_denied_path(root, env_deny=env_deny):
        return DoctorCheck(
            check="denied_paths",
            status=CheckStatus.FAIL,
            message=f"Workspace root {root} is in deny list",
        )
    return DoctorCheck(
        check="denied_paths",
        status=CheckStatus.PASS,
        message="Denied-path check passed",
    )


def _check_state_dir_writable(root: Path) -> DoctorCheck:
    """Verify .nexusos/ directory is writable."""
    state_dir = root / ".nexusos"
    if not state_dir.is_dir():
        return DoctorCheck(
            check="state_dir_writable",
            status=CheckStatus.WARNING,
            message=".nexusos/ directory missing — may not be writable",
        )
    test_file = state_dir / ".doctor_write_test"
    try:
        test_file.write_text("test")
        test_file.unlink()
        return DoctorCheck(
            check="state_dir_writable",
            status=CheckStatus.PASS,
            message=".nexusos/ state directory is writable",
        )
    except OSError as exc:
        return DoctorCheck(
            check="state_dir_writable",
            status=CheckStatus.FAIL,
            message=".nexusos/ state directory is not writable",
            detail=str(exc),
        )


def _check_config_parsable(root: Path) -> DoctorCheck:
    """Verify nexusos.toml exists and parses."""
    try:
        load_config_effective(root)
        return DoctorCheck(
            check="config_parsing",
            status=CheckStatus.PASS,
            message="nexusos.toml parses successfully",
        )
    except ConfigError as exc:
        return DoctorCheck(
            check="config_parsing",
            status=CheckStatus.FAIL,
            message="Configuration error",
            detail=str(exc),
        )


def _check_template_files(root: Path) -> DoctorCheck:
    """Verify required template files are present."""
    required = ["nexusos.toml", "README.md"]
    missing = [f for f in required if not (root / f).is_file()]
    if missing:
        return DoctorCheck(
            check="template_files",
            status=CheckStatus.WARNING,
            message=f"Missing template files: {', '.join(missing)}",
        )
    return DoctorCheck(
        check="template_files",
        status=CheckStatus.PASS,
        message="Required template files present",
    )


def _check_nested_workspaces(root: Path) -> DoctorCheck:
    """Detect unsupported nested workspace conditions."""
    from nexusos.core.path_safety import find_nearest_workspace_root, find_nested_workspaces

    # Check if parent is a workspace
    if root.parent != root:
        ancestor = find_nearest_workspace_root(root.parent)
        if ancestor is not None:
            return DoctorCheck(
                check="nested_workspaces",
                status=CheckStatus.FAIL,
                message=f"Parent directory {ancestor} is a NexusOS workspace",
            )

    # Check for nested workspaces below (exclude self)
    nested = find_nested_workspaces(root)
    nested = [n for n in nested if n.resolve() != root.resolve()]
    if nested:
        return DoctorCheck(
            check="nested_workspaces",
            status=CheckStatus.WARNING,
            message=f"Nested workspace(s) detected: {', '.join(str(p) for p in nested)}",
        )
    return DoctorCheck(
        check="nested_workspaces",
        status=CheckStatus.PASS,
        message="No nested workspace issues",
    )


def _check_source_dirs_untouched(root: Path) -> DoctorCheck:
    """Verify source directories are still intact (read-only contract)."""
    check_dirs = [
        "wiki",
        "raw",
        "ops",
        "mocs",
        "journal",
        "inbox",
    ]
    missing = [d for d in check_dirs if not (root / d).is_dir()]
    if missing:
        # Only warn — blank template doesn't have these
        return DoctorCheck(
            check="source_dirs",
            status=CheckStatus.WARNING,
            message=f"Source directories missing: {', '.join(missing)} (may be blank template)",
        )
    return DoctorCheck(
        check="source_dirs",
        status=CheckStatus.PASS,
        message="Source directories present",
    )


def run_doctor(
    path: Path | None = None,
    *,
    env_deny: str | None = None,
) -> DoctorReport:
    """Run the full doctor diagnostic suite."""
    target = path or Path.cwd()
    target = target.resolve(strict=False)

    checks: list[DoctorCheck] = []

    # Always-run checks (no workspace needed)
    checks.append(_check_python_version())
    checks.append(_check_fts5())

    # Workspace-dependent checks
    ws_check, root = _check_workspace_detection(target)
    checks.append(ws_check)

    if root is not None:
        checks.append(_check_workspace_id(root))
        checks.append(_check_root_boundary(root))
        checks.append(_check_denied_path(root, env_deny))
        checks.append(_check_state_dir_writable(root))
        checks.append(_check_config_parsable(root))
        checks.append(_check_template_files(root))
        checks.append(_check_nested_workspaces(root))
        checks.append(_check_source_dirs_untouched(root))

    passed = sum(1 for c in checks if c.status == CheckStatus.PASS)
    warnings = sum(1 for c in checks if c.status == CheckStatus.WARNING)
    failures = sum(1 for c in checks if c.status == CheckStatus.FAIL)
    healthy = failures == 0

    return DoctorReport(
        workspace_root=root,
        checks=checks,
        passed=passed,
        warnings=warnings,
        failures=failures,
        healthy=healthy,
    )

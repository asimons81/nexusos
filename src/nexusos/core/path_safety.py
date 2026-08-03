"""Path safety utilities — boundary checking, deny-paths, symlink detection."""

from __future__ import annotations

import os
from pathlib import Path

from nexusos.core.errors import (
    DeniedPathError,
    NestedWorkspaceError,
    PathSafetyError,
    RootOrHomeError,
    SymlinkEscapeError,
)

# Reserved native prefixes — never allowed as workspace targets.
# Keep the full public tuple for documentation and introspection, but compare
# only prefixes meaningful on the current operating system.
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/run",
    "/var/run",
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
)

_POSIX_FORBIDDEN_PREFIXES = FORBIDDEN_PREFIXES[:7]
_WINDOWS_FORBIDDEN_PREFIXES = FORBIDDEN_PREFIXES[7:]


def _parse_deny_list(env_var: str | None) -> list[str]:
    """Parse NEXUSOS_DENY_PATHS using the OS path separator."""
    if not env_var:
        return []
    raw = env_var.strip()
    if not raw:
        return []
    separator = os.pathsep  # : on Unix, ; on Windows
    return [p.strip() for p in raw.split(separator) if p.strip()]


def _native_forbidden_prefixes() -> tuple[str, ...]:
    """Return built-in prefixes meaningful on the current platform."""
    if os.name == "nt":
        return _WINDOWS_FORBIDDEN_PREFIXES
    return _POSIX_FORBIDDEN_PREFIXES


def _is_within(path: Path, boundary: Path) -> bool:
    """Return whether a resolved path is equal to or below a boundary."""
    try:
        path.relative_to(boundary)
    except ValueError:
        return False
    return True


def is_denied_path(target: Path, *, env_deny: str | None = None) -> bool:
    """Check whether a path is in the deny list."""
    if env_deny is None:
        env_deny = os.environ.get("NEXUSOS_DENY_PATHS")
    deny_list = _parse_deny_list(env_deny)
    resolved = target.expanduser().resolve(strict=False)

    for deny in deny_list:
        deny_path = Path(deny).expanduser().resolve(strict=False)
        if _is_within(resolved, deny_path):
            return True

    # Resolve native built-in prefixes before comparison. This matters on
    # systems such as macOS where /etc resolves to /private/etc.
    for prefix in _native_forbidden_prefixes():
        prefix_path = Path(prefix).resolve(strict=False)
        if _is_within(resolved, prefix_path):
            return True

    return False


def deny(target: Path, *, env_deny: str | None = None) -> None:
    """Raise DeniedPathError if the path is denied."""
    if is_denied_path(target, env_deny=env_deny):
        raise DeniedPathError(
            f"Path {target} is denied by NEXUSOS_DENY_PATHS or built-in rules",
            exit_code=2,
        )


def is_root_or_home(target: Path) -> bool:
    """Check if target is the filesystem root or user's home directory."""
    resolved = target.resolve(strict=False)
    return resolved in (
        Path("/").resolve(),
        Path.home().resolve(),
        Path("C:\\"),
    )


def forbid_root_or_home(target: Path) -> None:
    """Raise if target is root or home."""
    if is_root_or_home(target):
        raise RootOrHomeError(
            f"Cannot initialize workspace at {target} — refused (root or home directory)",
            exit_code=2,
        )


def find_nearest_workspace_root(start: Path) -> Path | None:
    """Walk up from start looking for .nexusos/workspace.json."""
    current = start.resolve(strict=False)
    while True:
        ws_file = current / ".nexusos" / "workspace.json"
        if ws_file.is_file():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def find_nested_workspaces(target: Path) -> list[Path]:
    """Find any .nexusos/ directories beneath target (nested workspace check)."""
    resolved = target.resolve(strict=False)
    if not resolved.is_dir():
        return []
    results: list[Path] = []
    try:
        for item in resolved.rglob(".nexusos/workspace.json"):
            results.append(item.parent.parent)
    except PermissionError:
        pass
    return results


def check_nesting(target: Path) -> None:
    """Check for nested workspace conditions.

    Fails if:
    - An ancestor is already a workspace
    - Any descendant is already a workspace
    """
    resolved = target.resolve(strict=False)

    # Check ancestor
    ancestor = find_nearest_workspace_root(resolved.parent)
    if ancestor is not None:
        raise NestedWorkspaceError(
            f"Cannot initialize inside existing workspace at {ancestor}",
            exit_code=2,
        )

    # Check descendants (only if target already exists as dir)
    if resolved.is_dir():
        nested = find_nested_workspaces(resolved)
        # Filter out: the target itself is not a "nested" workspace
        nested = [n for n in nested if n.resolve() != resolved.resolve()]
        if nested:
            raise NestedWorkspaceError(
                "Cannot initialize: workspace(s) exist below target: "
                + ", ".join(str(p) for p in nested),
                exit_code=2,
            )


def check_symlink_escape(target: Path, workspace_root: Path) -> None:
    """Verify no symlink inside workspace_root points outside it."""
    resolved_root = workspace_root.resolve(strict=False)
    try:
        for entry in resolved_root.rglob("*"):
            if not entry.is_symlink():
                continue
            link_target = os.readlink(str(entry))
            link_path = Path(link_target)
            if not link_path.is_absolute():
                link_path = (entry.parent / link_path).resolve(strict=False)
            else:
                link_path = link_path.resolve(strict=False)
            try:
                link_path.relative_to(resolved_root)
            except ValueError:
                raise SymlinkEscapeError(
                    f"Symlink {entry} points outside workspace: {link_path}",
                    exit_code=2,
                )
    except PermissionError:
        pass


def resolve_safe(target: Path, *, env_deny: str | None = None) -> Path:
    """Resolve a path with full safety checks (deny, root/home, nesting)."""
    deny(target, env_deny=env_deny)
    forbid_root_or_home(target)
    return target.resolve(strict=False)


def workspace_root(target: Path) -> Path | None:
    """Find the nearest workspace root starting from target."""
    return find_nearest_workspace_root(target)


def validate_within_workspace(path: Path, workspace: Path) -> None:
    """Validate that a path is within the workspace boundary (resolved)."""
    resolved_ws = workspace.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_ws)
    except ValueError:
        raise PathSafetyError(
            f"Path {path} is outside workspace {workspace}",
            exit_code=2,
        )

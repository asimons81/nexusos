"""File scanner for deterministic workspace discovery.

Discovers Markdown and plain-text files, applies include/exclude patterns,
resolves collections, and returns typed discovery results. Never parses
document content — that belongs to ``nexusos.parsing``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from nexusos.core.models import NexusOSConfig
from nexusos.discovery.models import DiscoveredFile, DiscoveryResult

# Default exclusions always applied by the scanner. Whole-subtree patterns
# (``X/**``) are also used to prune excluded directories during the walk so
# excluded trees are never read and never emit unreadable-directory warnings.
_DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    ".git/**",
    ".nexusos/**",
    "node_modules/**",
    ".venv/**",
    "**/.DS_Store",
    "**/Thumbs.db",
    "**/Zone.Identifier",
    "**/__pycache__/**",
    "**/.direnv/**",
]


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile glob-like patterns to regex.

    ``**`` matches across directory boundaries; when followed by a ``/`` it
    also matches zero directories, so ``**/*.md`` matches both ``a/b.md`` and
    a root-level ``b.md`` (pathlib.glob / gitignore semantics). ``*`` matches
    within a single path segment and ``?`` matches one non-slash character.
    """
    result: list[re.Pattern[str]] = []
    for pat in patterns:
        # Convert glob to regex: ** → .*, * → [^/]*, ? → [^/]
        rx = re.escape(pat)
        rx = rx.replace(r"\*\*", "___DOUBLESTAR___")
        rx = rx.replace(r"\*", "[^/]*")
        # Globstar followed by a slash matches zero or more directories.
        rx = rx.replace("___DOUBLESTAR___/", "(?:.*/)?")
        # A bare globstar (not followed by a slash) matches everything.
        rx = rx.replace("___DOUBLESTAR___", ".*")
        result.append(re.compile("^" + rx + "$"))
    return result


def _match_any(compiled: list[re.Pattern[str]], value: str) -> bool:
    return any(p.match(value) for p in compiled)


_INDEXED_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".txt"})


def _resolve_collection(normalized_path: str, config: NexusOSConfig) -> str:
    """Resolve a document's collection from the longest matching configured path.

    Collections are resolved by matching path prefixes against the configured
    ``collection_mappings`` dict. The longest match wins. Falls back to
    ``config.default_collection``.
    """
    best_match = ""
    best_collection = config.default_collection
    for dir_name, collection_name in config.collection_mappings.items():
        if (normalized_path.startswith(dir_name + "/") or normalized_path == dir_name) and len(
            dir_name
        ) > len(best_match):
            best_match = dir_name
            best_collection = collection_name
    return best_collection


def _normalize_path(relative: str) -> str:
    """Normalize to forward-slash form, strip leading './'."""
    path = relative.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _prune_patterns(patterns: list[str]) -> list[str]:
    """Return only whole-subtree patterns (ending in ``/**``).

    Only these may prune a directory during the walk: for ``X/**`` every
    file under a matching directory is excluded, so descending is wasted
    work and any unreadable-dir error inside is irrelevant. File-scoped
    patterns such as ``**/x`` match individual files and must never prune
    a directory — otherwise ``**/x`` would silently drop every subtree that
    contains a file named ``x`` (F2 review finding).
    """
    return [p for p in patterns if p.endswith("/**")]


def _walk_workspace(
    root: Path,
    prune_rx: list[re.Pattern[str]],
) -> tuple[list[Path], list[dict[str, Any]]]:
    """Explicitly walk the tree, reporting unreadable directories.

    Replaces ``root.glob("**/*")``, which silently skips permission-denied
    subdirectories. Every directory that raises an ``OSError`` during
    traversal is surfaced as an ``unreadable_directory`` warning so an
    unreadable subtree can never be a silent success. Directories matched
    by whole-subtree exclusion patterns are pruned before descent, so
    excluded trees are never read and never produce noise warnings.

    Returns ``(files, warnings)`` with files sorted by normalized relative
    path for deterministic ordering.
    """
    files: list[Path] = []
    warnings: list[dict[str, Any]] = []

    def _onerror(exc: OSError) -> None:
        failed = Path(exc.filename) if exc.filename else root
        try:
            rel = failed.resolve(strict=False).relative_to(root.resolve(strict=False))
            normalized = _normalize_path(str(rel))
        except (OSError, ValueError):
            normalized = str(failed)
        if normalized in ("", "."):
            warnings.append(
                {
                    "type": "discovery_error",
                    "message": f"cannot scan workspace: {exc}",
                }
            )
        else:
            warnings.append(
                {
                    "type": "unreadable_directory",
                    "path": normalized,
                    "message": str(exc),
                }
            )

    def _is_pruned_dir(normalized_dir: str) -> bool:
        # A directory is pruned when a placeholder file under it would be
        # excluded by a whole-subtree pattern (``X/**``). File-only patterns
        # never appear in ``prune_rx``, so they cannot prune a directory.
        probe = f"{normalized_dir}/x" if normalized_dir else "x"
        return _match_any(prune_rx, probe)

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror, followlinks=False):
        dir_rel = Path(dirpath).relative_to(root)
        dir_norm = _normalize_path(str(dir_rel)) if str(dir_rel) != "." else ""
        dirnames[:] = [
            d for d in dirnames if not _is_pruned_dir(f"{dir_norm}/{d}" if dir_norm else d)
        ]
        for name in filenames:
            files.append(Path(dirpath) / name)

    files.sort(key=lambda p: _normalize_path(str(p.relative_to(root))))
    return files, warnings


def scan_unreadable_directories(
    root: Path,
    exclude_patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return unreadable-directory and discovery-error warnings under root.

    Read-only helper used by doctor: walks the tree with the default
    exclusions plus the caller's config exclude patterns and returns the
    warnings describing directories that could not be read.
    """
    patterns = _prune_patterns(exclude_patterns or []) + _prune_patterns(_DEFAULT_EXCLUDE_PATTERNS)
    prune_rx = _compile_patterns(patterns)
    _, warnings = _walk_workspace(root, prune_rx)
    return [w for w in warnings if w.get("type") in ("unreadable_directory", "discovery_error")]


def scan_workspace(
    workspace_root: Path,
    config: NexusOSConfig,
) -> DiscoveryResult:
    """Scan a workspace for indexable source files.

    Returns a typed :class:`DiscoveryResult` with discovered files and
    any non-fatal warnings encountered during scanning.
    """
    root = workspace_root.resolve(strict=False)
    include_rx = _compile_patterns(config.include_patterns)
    exclude_rx = _compile_patterns(config.exclude_patterns)

    # Default exclusions that are always applied
    default_exclude_rx = _compile_patterns(_DEFAULT_EXCLUDE_PATTERNS)

    # Whole-subtree patterns only: file-scoped excludes must never prune
    # directories during the walk (F2 review finding).
    prune_rx = _compile_patterns(
        _prune_patterns(config.exclude_patterns) + _prune_patterns(_DEFAULT_EXCLUDE_PATTERNS)
    )

    discovered: dict[str, DiscoveredFile] = {}
    warnings: list[dict[str, Any]] = []

    try:
        walked, walk_warnings = _walk_workspace(root, prune_rx)
    except OSError as exc:
        return DiscoveryResult(
            files=[],
            warnings=[
                {
                    "type": "discovery_error",
                    "message": f"cannot scan workspace: {exc}",
                }
            ],
        )
    warnings.extend(walk_warnings)
    files = walked

    for file_path in files:
        if not file_path.is_file():
            continue

        try:
            relative_str = str(file_path.relative_to(root))
        except ValueError:
            warnings.append(
                {
                    "type": "boundary_warning",
                    "message": f"file outside workspace boundary: {file_path}",
                }
            )
            continue

        normalized = _normalize_path(relative_str)

        # Default exclusions
        if _match_any(default_exclude_rx, normalized):
            continue

        # Config exclusions
        if _match_any(exclude_rx, normalized):
            continue

        # Extension check (case-insensitive)
        suffix_lower = file_path.suffix.lower()
        if suffix_lower not in _INDEXED_EXTENSIONS:
            continue

        # Include check
        if not _match_any(include_rx, normalized):
            continue

        # Symlink handling
        if file_path.is_symlink():
            if config.symlink_policy == "deny":
                warnings.append(
                    {
                        "type": "symlink_denied",
                        "message": f"symlink denied by policy: {normalized}",
                    }
                )
                continue
            elif config.symlink_policy == "warn":
                warnings.append(
                    {
                        "type": "symlink_warning",
                        "message": f"symlink detected: {normalized}",
                    }
                )
            # resolve symlink target and check boundary
            try:
                real = file_path.resolve(strict=False)
                real.relative_to(root.resolve(strict=False))
            except ValueError:
                warnings.append(
                    {
                        "type": "symlink_escape",
                        "message": f"symlink escapes workspace: {normalized} → {real}",
                    }
                )
                continue
            except OSError:
                warnings.append(
                    {
                        "type": "unreadable_symlink",
                        "message": f"cannot resolve symlink: {normalized}",
                    }
                )
                continue

        # File size check
        try:
            st = file_path.stat()
        except OSError as exc:
            warnings.append(
                {
                    "type": "unreadable_file",
                    "path": normalized,
                    "message": str(exc),
                }
            )
            continue

        if st.st_size > config.max_file_size_bytes:
            warnings.append(
                {
                    "type": "file_too_large",
                    "path": normalized,
                    "message": (
                        f"file {st.st_size} bytes exceeds limit {config.max_file_size_bytes}"
                    ),
                }
            )
            continue

        collection = _resolve_collection(normalized, config)

        mtime_ns = st.st_mtime_ns

        discovered[normalized] = DiscoveredFile(
            relative_path=relative_str,
            normalized_path=normalized,
            collection=collection,
            file_type="markdown" if suffix_lower in (".md", ".markdown") else "plaintext",
            size_bytes=st.st_size,
            mtime_ns=mtime_ns,
        )

    files_list = sorted(discovered.values(), key=lambda f: f.normalized_path)
    return DiscoveryResult(files=files_list, warnings=warnings)

"""File scanner for deterministic workspace discovery.

Discovers Markdown and plain-text files, applies include/exclude patterns,
resolves collections, and returns typed discovery results. Never parses
document content — that belongs to ``nexusos.parsing``.
"""

from __future__ import annotations

import re
from pathlib import Path  # noqa: TC003
from typing import Any

from nexusos.core.models import NexusOSConfig
from nexusos.discovery.models import DiscoveredFile, DiscoveryResult


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile glob-like patterns to regex."""
    result: list[re.Pattern[str]] = []
    for pat in patterns:
        # Convert glob to regex: ** → .*, * → [^/]*, ? → [^/]
        rx = re.escape(pat)
        rx = rx.replace(r"\*\*", "___DOUBLESTAR___")
        rx = rx.replace(r"\*", "[^/]*")
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
    default_exclude_rx = _compile_patterns(
        [
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
    )

    discovered: dict[str, DiscoveredFile] = {}
    warnings: list[dict[str, Any]] = []

    try:
        files = sorted(
            root.glob("**/*"),
            key=lambda p: _normalize_path(str(p.relative_to(root))),
        )
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

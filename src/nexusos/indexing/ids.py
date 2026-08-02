"""Deterministic, workspace-scoped identifiers for the indexing kernel.

Document IDs are derived from ``workspace_id + normalized relative path`` so
they are stable across reindexing and content changes, distinct between
workspaces, URL-safe, bounded in length, and free of absolute path or machine
identity data. Chunk IDs additionally incorporate the chunk ordinal and a
content hash so they change when chunk content changes. Run IDs use secure
randomness (allowed by the Phase 2 contract).
"""

from __future__ import annotations

import hashlib
import secrets
import string

DOC_ID_PREFIX = "nxo_doc_"
CHUNK_ID_PREFIX = "nxo_chk_"
RUN_ID_PREFIX = "nxo_run_"

_ID_ALPHABET = string.ascii_lowercase + string.digits

#: Length of the hex digest appended after a prefix.
_ID_HASH_LENGTH = 32


def _normalize_relative_path(relative_path: str) -> str:
    """Normalize a relative path to forward-slash form without leading './'."""
    path = relative_path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _truncated_sha256(data: bytes, length: int = _ID_HASH_LENGTH) -> str:
    """Return the first ``length`` hex characters of the SHA-256 digest."""
    return hashlib.sha256(data).hexdigest()[:length]


def document_id(workspace_id: str, normalized_path: str) -> str:
    """Return a stable, workspace-scoped document identifier.

    Identical inputs always produce the identical ID; the ID does not change
    when a document's content changes, and different workspaces never collide.
    """
    path = _normalize_relative_path(normalized_path)
    digest = _truncated_sha256(f"{workspace_id}\0{path}".encode())
    return f"{DOC_ID_PREFIX}{digest}"


def chunk_id(document_id: str, ordinal: int, content_sha256: str) -> str:
    """Return a deterministic chunk identifier.

    Derived from ``document_id + ordinal + content hash`` so any change to the
    chunk's content or position produces a different ID.
    """
    digest = _truncated_sha256(f"{document_id}\0{ordinal}\0{content_sha256}".encode())
    return f"{CHUNK_ID_PREFIX}{digest}"


def run_id() -> str:
    """Return a random index-run identifier (runs may use secure randomness)."""
    suffix = "".join(secrets.choice(_ID_ALPHABET) for _ in range(16))
    return f"{RUN_ID_PREFIX}{suffix}"

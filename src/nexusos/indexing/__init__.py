"""Indexing kernel for NexusOS: deterministic, incrementally maintained SQLite index.

This package is the internal persistence foundation for Phase 2. It provides
workspace-scoped identifiers, the SQLite schema and migrations, the workspace
lock, and the :class:`IndexKernel` API (add/update/remove documents, run
records, and deterministic candidate lookup). Search, evidence packets, graph
queries, and CLI surfaces are intentionally out of scope here.
"""

from __future__ import annotations

from nexusos.indexing.ids import chunk_id, document_id, run_id
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.lock import IndexLock
from nexusos.indexing.models import (
    DocumentCandidate,
    IndexCounts,
    IndexedChunk,
    IndexedDocument,
    IndexedHeading,
    IndexedLink,
    IndexRunRecord,
)
from nexusos.indexing.schema import SCHEMA_VERSION

__all__ = [
    "SCHEMA_VERSION",
    "DocumentCandidate",
    "IndexCounts",
    "IndexKernel",
    "IndexLock",
    "IndexRunRecord",
    "IndexedChunk",
    "IndexedDocument",
    "IndexedHeading",
    "IndexedLink",
    "chunk_id",
    "document_id",
    "run_id",
]

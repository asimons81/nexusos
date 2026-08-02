"""SQLite schema for the NexusOS index database (derived state).

The database lives at ``.nexusos/index.sqlite3`` by default, is derived state
(deleting it and reindexing fully reconstructs it), and must never be created
by ``doctor`` or ``status``. The schema mirrors the Phase 2 contract: meta,
documents, headings, chunks, an FTS5 preparation table (``chunks_fts``), wiki
links, and index-run records.
"""

from __future__ import annotations

#: Current index schema version, stored in ``PRAGMA user_version``.
SCHEMA_VERSION = 1

_META = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    normalized_path TEXT NOT NULL UNIQUE,
    collection TEXT NOT NULL,
    title TEXT NOT NULL,
    file_type TEXT NOT NULL,
    authority_class TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    mtime_ns INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    frontmatter_json TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    line_count INTEGER NOT NULL,
    parse_warning_count INTEGER NOT NULL DEFAULT 0
)
"""

_HEADINGS = """
CREATE TABLE IF NOT EXISTS headings (
    heading_id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    level INTEGER NOT NULL,
    text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    line INTEGER NOT NULL,
    heading_path_json TEXT NOT NULL
)
"""

_CHUNKS = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    heading_path_json TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
)
"""

_CHUNKS_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    title,
    relative_path UNINDEXED,
    heading_path,
    text,
    tags,
    tokenize = 'unicode61'
)
"""

_LINKS = """
CREATE TABLE IF NOT EXISTS links (
    link_id INTEGER PRIMARY KEY,
    source_document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_line INTEGER NOT NULL,
    raw_target TEXT NOT NULL,
    target_slug TEXT NOT NULL,
    target_heading TEXT,
    label TEXT,
    target_document_id TEXT REFERENCES documents(document_id) ON DELETE SET NULL,
    resolved INTEGER NOT NULL,
    resolution_state TEXT NOT NULL
)
"""

_RUNS = """
CREATE TABLE IF NOT EXISTS index_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    mode TEXT NOT NULL,
    files_seen INTEGER NOT NULL DEFAULT 0,
    files_added INTEGER NOT NULL DEFAULT 0,
    files_updated INTEGER NOT NULL DEFAULT 0,
    files_unchanged INTEGER NOT NULL DEFAULT 0,
    files_deleted INTEGER NOT NULL DEFAULT 0,
    documents_failed INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
)
"""

_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_headings_document ON headings(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_document_id)",
    "CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_document_id)",
    "CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection)",
)

#: Statements executed in order when creating schema version 1.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    _META,
    _DOCUMENTS,
    _HEADINGS,
    _CHUNKS,
    _CHUNKS_FTS,
    _LINKS,
    _RUNS,
    *_INDEXES,
)

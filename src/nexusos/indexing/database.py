"""Low-level SQLite persistence for the NexusOS indexing kernel.

``IndexDatabase`` owns the connection, schema migration, transactions, and all
row CRUD for documents, headings, chunks, the FTS5 preparation table, wiki
links, and index-run records. It does not own the workspace lock or the
deterministic-ID policy; those live in :mod:`nexusos.indexing.lock` and
:mod:`nexusos.indexing.kernel`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator  # noqa: TC003
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from nexusos.core.errors import (
    CorruptDatabaseError,
    DatabaseError,
    IndexEntryExistsError,
    IndexEntryNotFoundError,
    IndexTransactionError,
)
from nexusos.indexing.ids import run_id
from nexusos.indexing.migrations import migrate
from nexusos.indexing.models import (
    DocumentCandidate,
    IndexCounts,
    IndexedChunk,
    IndexedDocument,
    IndexedHeading,
    IndexedLink,
    IndexRunRecord,
)


def iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _as_str(row: Any, key: str) -> str:
    return str(row[key])


def _as_int(row: Any, key: str) -> int:
    return int(row[key])


def _as_optional_str(row: Any, key: str) -> str | None:
    value = row[key]
    return None if value is None else str(value)


class IndexDatabase:
    """A workspace-bound SQLite index database with explicit transactions."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._tx_depth = 0

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def in_transaction(self) -> bool:
        return self._tx_depth > 0

    def open(self, *, create_parent: bool = False) -> None:
        """Open (and if needed create) the database and migrate it.

        ``create_parent`` must be True when the caller explicitly invoked an
        index operation; otherwise a missing state directory is an error so
        read-only tooling can never create the index database.
        """
        if self._conn is not None:
            raise DatabaseError("index database is already open")
        if not self._db_path.parent.is_dir():
            if not create_parent:
                raise DatabaseError(
                    f"state directory does not exist: {self._db_path.parent}; "
                    "pass create_parent=True when indexing is explicitly invoked"
                )
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        except sqlite3.Error as exc:
            raise DatabaseError(f"cannot open index database {self._db_path}: {exc}")
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None  # explicit transaction control
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.DatabaseError as exc:
            conn.close()
            raise CorruptDatabaseError(f"index database is corrupt or invalid: {exc}")
        except sqlite3.OperationalError as exc:
            conn.close()
            raise DatabaseError(f"cannot configure index database: {exc}")
        try:
            migrate(conn)
        except sqlite3.DatabaseError as exc:
            conn.close()
            raise CorruptDatabaseError(f"index database is corrupt or invalid: {exc}")
        except sqlite3.OperationalError as exc:
            conn.close()
            raise DatabaseError(f"cannot initialize index schema: {exc}")
        self._conn = conn

    def close(self) -> None:
        """Close the database, rolling back any open transaction."""
        conn = self._conn
        if conn is None:
            return
        if self.in_transaction:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
        self._tx_depth = 0
        conn.close()
        self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run a block inside a single write transaction.

        Nested transactions are rejected; callers can batch multiple kernel
        operations in one transaction for atomicity.
        """
        conn = self._require_open()
        if self.in_transaction:
            raise IndexTransactionError("nested index transactions are not supported")
        self._tx_depth += 1
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            self._tx_depth -= 1
            raise IndexTransactionError(f"cannot begin index transaction: {exc}")
        try:
            yield
        except BaseException:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            self._tx_depth -= 1
            raise
        else:
            try:
                conn.execute("COMMIT")
            except sqlite3.Error as exc:
                self._tx_depth -= 1
                raise IndexTransactionError(f"cannot commit index transaction: {exc}")
            self._tx_depth -= 1

    # -- meta -----------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self._fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return None if row is None else _as_str(row, "value")

    def set_meta(self, key: str, value: str) -> None:
        self._execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # -- documents ------------------------------------------------------------

    def insert_document(self, doc: IndexedDocument) -> None:
        """Insert a new document; raises if the relative path is already indexed."""
        self._require_open()
        row = self._fetchone(
            "SELECT document_id FROM documents WHERE relative_path = ?", (doc.relative_path,)
        )
        if row is not None:
            raise IndexEntryExistsError(f"document already indexed: {doc.relative_path}")
        self._insert_document_rows(doc)

    def replace_document(self, doc: IndexedDocument) -> None:
        """Replace an existing document's rows; raises if it does not exist.

        The document keeps its identity; incoming links are NOT touched (the
        document still exists after an update). When the document id is
        unchanged the documents row is updated in place so the ``ON DELETE
        SET NULL`` foreign key on incoming links never fires.
        """
        self._require_open()
        row = self._fetchone(
            "SELECT document_id FROM documents WHERE relative_path = ?", (doc.relative_path,)
        )
        if row is None:
            raise IndexEntryNotFoundError(f"document is not indexed: {doc.relative_path}")
        old_document_id = _as_str(row, "document_id")
        if old_document_id == doc.document_id:
            self._remove_document_content(old_document_id, keep_document_row=True)
            self._update_document_row(doc)
            self._insert_document_children(doc)
        else:
            # Identity changed: the old document is fully removed (its incoming
            # links are reset), then the document is inserted fresh.
            self._remove_document_content(old_document_id)
            self._insert_document_rows(doc)

    def upsert_document(self, doc: IndexedDocument) -> None:
        """Insert or replace a document by relative path."""
        self._require_open()
        row = self._fetchone(
            "SELECT document_id FROM documents WHERE relative_path = ?", (doc.relative_path,)
        )
        if row is None:
            self._insert_document_rows(doc)
            return
        old_document_id = _as_str(row, "document_id")
        if old_document_id == doc.document_id:
            self._remove_document_content(old_document_id, keep_document_row=True)
            self._update_document_row(doc)
            self._insert_document_children(doc)
        else:
            self._remove_document_content(old_document_id)
            self._insert_document_rows(doc)

    def delete_document(self, relative_path: str) -> bool:
        """Remove a document and all rows it owns.

        Incoming links that pointed at the removed document are reset to
        ``unresolved`` so no link ever reports ``resolved`` for a missing
        document. Returns False when no such document exists.
        """
        self._require_open()
        row = self._fetchone(
            "SELECT document_id FROM documents WHERE relative_path = ?", (relative_path,)
        )
        if row is None:
            return False
        document_id = _as_str(row, "document_id")
        self._execute(
            "UPDATE links SET target_document_id = NULL, resolved = 0, "
            "resolution_state = 'unresolved' WHERE target_document_id = ?",
            (document_id,),
        )
        self._remove_document_content(document_id)
        return True

    def get_document(self, relative_path: str) -> IndexedDocument | None:
        """Return the full stored document (including derived rows), or None."""
        self._require_open()
        row = self._fetchone("SELECT * FROM documents WHERE relative_path = ?", (relative_path,))
        if row is None:
            return None
        document_id = _as_str(row, "document_id")
        headings = [
            IndexedHeading(
                ordinal=_as_int(h, "ordinal"),
                level=_as_int(h, "level"),
                text=_as_str(h, "text"),
                normalized_text=_as_str(h, "normalized_text"),
                line=_as_int(h, "line"),
                heading_path=tuple(json.loads(_as_str(h, "heading_path_json"))),
            )
            for h in self._fetchall(
                "SELECT * FROM headings WHERE document_id = ? ORDER BY ordinal",
                (document_id,),
            )
        ]
        chunks = [
            IndexedChunk(
                chunk_id=_as_str(c, "chunk_id"),
                document_id=_as_str(c, "document_id"),
                ordinal=_as_int(c, "ordinal"),
                heading_path=tuple(json.loads(_as_str(c, "heading_path_json"))),
                start_line=_as_int(c, "start_line"),
                end_line=_as_int(c, "end_line"),
                text=_as_str(c, "text"),
                content_sha256=_as_str(c, "content_sha256"),
            )
            for c in self._fetchall(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal", (document_id,)
            )
        ]
        wikilinks = [
            IndexedLink(
                source_line=_as_int(link_row, "source_line"),
                raw_target=_as_str(link_row, "raw_target"),
                target_slug=_as_str(link_row, "target_slug"),
                target_heading=_as_optional_str(link_row, "target_heading"),
                label=_as_optional_str(link_row, "label"),
                target_document_id=_as_optional_str(link_row, "target_document_id"),
                resolved=bool(_as_int(link_row, "resolved")),
                resolution_state=_as_str(link_row, "resolution_state"),
            )
            for link_row in self._fetchall(
                "SELECT * FROM links WHERE source_document_id = ? ORDER BY source_line, link_id",
                (document_id,),
            )
        ]
        tags_row = self._fetchone(
            "SELECT tags FROM chunks_fts WHERE document_id = ? ORDER BY rowid LIMIT 1",
            (document_id,),
        )
        tags = [] if tags_row is None else [t for t in str(tags_row["tags"]).split() if t]
        return IndexedDocument(
            document_id=document_id,
            relative_path=_as_str(row, "relative_path"),
            normalized_path=_as_str(row, "normalized_path"),
            collection=_as_str(row, "collection"),
            title=_as_str(row, "title"),
            file_type=_as_str(row, "file_type"),
            authority_class=_as_str(row, "authority_class"),
            created_at=_as_optional_str(row, "created_at"),
            updated_at=_as_optional_str(row, "updated_at"),
            mtime_ns=_as_int(row, "mtime_ns"),
            size_bytes=_as_int(row, "size_bytes"),
            content_sha256=_as_str(row, "content_sha256"),
            frontmatter_json=_as_str(row, "frontmatter_json"),
            indexed_at=_as_str(row, "indexed_at"),
            line_count=_as_int(row, "line_count"),
            parse_warning_count=_as_int(row, "parse_warning_count"),
            headings=headings,
            chunks=chunks,
            wikilinks=wikilinks,
            tags=tags,
        )

    def get_candidate_by_normalized_path(self, normalized_path: str) -> DocumentCandidate | None:
        """Return a document candidate for an exact normalized-path match."""
        self._require_open()
        row = self._fetchone(
            "SELECT document_id, normalized_path, title, collection "
            "FROM documents WHERE normalized_path = ?",
            (normalized_path,),
        )
        if row is None:
            return None
        return DocumentCandidate(
            document_id=_as_str(row, "document_id"),
            normalized_path=_as_str(row, "normalized_path"),
            title=_as_str(row, "title"),
            collection=_as_str(row, "collection"),
        )

    def list_documents(self) -> list[DocumentCandidate]:
        """Return all document candidates in deterministic order."""
        self._require_open()
        rows = self._fetchall(
            "SELECT document_id, normalized_path, title, collection "
            "FROM documents ORDER BY normalized_path ASC, title ASC"
        )
        return [
            DocumentCandidate(
                document_id=_as_str(r, "document_id"),
                normalized_path=_as_str(r, "normalized_path"),
                title=_as_str(r, "title"),
                collection=_as_str(r, "collection"),
            )
            for r in rows
        ]

    def counts(self) -> IndexCounts:
        """Return row counts for status reporting."""
        self._require_open()

        def _count(sql: str) -> int:
            row = self._fetchone(sql)
            return 0 if row is None else int(row[0])

        return IndexCounts(
            document_count=_count("SELECT COUNT(*) FROM documents"),
            chunk_count=_count("SELECT COUNT(*) FROM chunks"),
            heading_count=_count("SELECT COUNT(*) FROM headings"),
            resolved_link_count=_count(
                "SELECT COUNT(*) FROM links WHERE resolution_state = 'resolved'"
            ),
            unresolved_link_count=_count(
                "SELECT COUNT(*) FROM links WHERE resolution_state = 'unresolved'"
            ),
            ambiguous_link_count=_count(
                "SELECT COUNT(*) FROM links WHERE resolution_state = 'ambiguous'"
            ),
        )

    # -- runs -----------------------------------------------------------------

    def begin_run(self, *, mode: str) -> IndexRunRecord:
        """Create an index-run record and return it (still incomplete)."""
        self._require_open()
        run = IndexRunRecord(run_id=run_id(), started_at=iso_now(), mode=mode)
        self._upsert_run(run)
        return run

    def complete_run(
        self,
        run: IndexRunRecord,
        *,
        success: bool,
        error_summary: str | None = None,
        files_seen: int = 0,
        files_added: int = 0,
        files_updated: int = 0,
        files_unchanged: int = 0,
        files_deleted: int = 0,
        documents_failed: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
    ) -> IndexRunRecord:
        """Mark a run complete, persist the counters, and return the record."""
        self._require_open()
        completed = run.model_copy(
            update={
                "completed_at": iso_now(),
                "success": success,
                "error_summary": error_summary,
                "files_seen": files_seen,
                "files_added": files_added,
                "files_updated": files_updated,
                "files_unchanged": files_unchanged,
                "files_deleted": files_deleted,
                "documents_failed": documents_failed,
                "warning_count": warning_count,
                "error_count": error_count,
            }
        )
        self._upsert_run(completed)
        return completed

    def get_last_run(self) -> IndexRunRecord | None:
        """Return the most recently started index run, or None."""
        self._require_open()
        row = self._fetchone(
            "SELECT * FROM index_runs ORDER BY started_at DESC, run_id DESC LIMIT 1"
        )
        if row is None:
            return None
        return IndexRunRecord(
            run_id=_as_str(row, "run_id"),
            started_at=_as_str(row, "started_at"),
            completed_at=_as_optional_str(row, "completed_at"),
            mode=_as_str(row, "mode"),
            files_seen=_as_int(row, "files_seen"),
            files_added=_as_int(row, "files_added"),
            files_updated=_as_int(row, "files_updated"),
            files_unchanged=_as_int(row, "files_unchanged"),
            files_deleted=_as_int(row, "files_deleted"),
            documents_failed=_as_int(row, "documents_failed"),
            warning_count=_as_int(row, "warning_count"),
            error_count=_as_int(row, "error_count"),
            success=bool(_as_int(row, "success")),
            error_summary=_as_optional_str(row, "error_summary"),
        )

    # -- private row helpers --------------------------------------------------

    def _insert_document_rows(self, doc: IndexedDocument) -> None:
        """Insert the documents row and all derived rows for a document."""
        self._insert_document_row(doc)
        self._insert_document_children(doc)

    def _insert_document_row(self, doc: IndexedDocument) -> None:
        self._execute(
            "INSERT INTO documents ("
            "document_id, relative_path, normalized_path, collection, title, "
            "file_type, authority_class, created_at, updated_at, mtime_ns, "
            "size_bytes, content_sha256, frontmatter_json, indexed_at, "
            "line_count, parse_warning_count"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc.document_id,
                doc.relative_path,
                doc.normalized_path,
                doc.collection,
                doc.title,
                doc.file_type,
                doc.authority_class,
                doc.created_at,
                doc.updated_at,
                doc.mtime_ns,
                doc.size_bytes,
                doc.content_sha256,
                doc.frontmatter_json,
                doc.indexed_at,
                doc.line_count,
                doc.parse_warning_count,
            ),
        )

    def _update_document_row(self, doc: IndexedDocument) -> None:
        """Update the documents row in place (identity-preserving replace)."""
        self._execute(
            "UPDATE documents SET "
            "relative_path = ?, normalized_path = ?, collection = ?, title = ?, "
            "file_type = ?, authority_class = ?, created_at = ?, updated_at = ?, "
            "mtime_ns = ?, size_bytes = ?, content_sha256 = ?, frontmatter_json = ?, "
            "indexed_at = ?, line_count = ?, parse_warning_count = ? "
            "WHERE document_id = ?",
            (
                doc.relative_path,
                doc.normalized_path,
                doc.collection,
                doc.title,
                doc.file_type,
                doc.authority_class,
                doc.created_at,
                doc.updated_at,
                doc.mtime_ns,
                doc.size_bytes,
                doc.content_sha256,
                doc.frontmatter_json,
                doc.indexed_at,
                doc.line_count,
                doc.parse_warning_count,
                doc.document_id,
            ),
        )

    def _insert_document_children(self, doc: IndexedDocument) -> None:
        """Insert derived rows (headings, chunks, FTS, links) for a document."""
        for heading in doc.headings:
            self._execute(
                "INSERT INTO headings ("
                "document_id, ordinal, level, text, normalized_text, line, heading_path_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    doc.document_id,
                    heading.ordinal,
                    heading.level,
                    heading.text,
                    heading.normalized_text,
                    heading.line,
                    json.dumps(list(heading.heading_path)),
                ),
            )
        for chunk in doc.chunks:
            self._execute(
                "INSERT INTO chunks ("
                "chunk_id, document_id, ordinal, heading_path_json, start_line, "
                "end_line, text, content_sha256"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.ordinal,
                    json.dumps(list(chunk.heading_path)),
                    chunk.start_line,
                    chunk.end_line,
                    chunk.text,
                    chunk.content_sha256,
                ),
            )
            self._execute(
                "INSERT INTO chunks_fts ("
                "chunk_id, document_id, title, relative_path, heading_path, text, tags"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    doc.title,
                    doc.normalized_path,
                    json.dumps(list(chunk.heading_path)),
                    chunk.text,
                    " ".join(doc.tags),
                ),
            )
        for link in doc.wikilinks:
            self._execute(
                "INSERT INTO links ("
                "source_document_id, source_line, raw_target, target_slug, "
                "target_heading, label, target_document_id, resolved, resolution_state"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc.document_id,
                    link.source_line,
                    link.raw_target,
                    link.target_slug,
                    link.target_heading,
                    link.label,
                    link.target_document_id,
                    1 if link.resolved else 0,
                    link.resolution_state,
                ),
            )

    def _remove_document_content(
        self, document_id: str, *, keep_document_row: bool = False
    ) -> None:
        """Remove all rows owned by a document (chunks, FTS, headings, links).

        When ``keep_document_row`` is True the documents row is preserved so
        incoming links (which reference it via ``ON DELETE SET NULL``) are not
        touched; callers that keep the row must re-insert or update it.
        """
        chunk_ids = [
            _as_str(r, "chunk_id")
            for r in self._fetchall(
                "SELECT chunk_id FROM chunks WHERE document_id = ?", (document_id,)
            )
        ]
        for chunk_id in chunk_ids:
            self._execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
        self._execute("DELETE FROM headings WHERE document_id = ?", (document_id,))
        self._execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        self._execute("DELETE FROM links WHERE source_document_id = ?", (document_id,))
        if not keep_document_row:
            self._execute("DELETE FROM documents WHERE document_id = ?", (document_id,))

    def _upsert_run(self, run: IndexRunRecord) -> None:
        self._execute(
            "INSERT INTO index_runs ("
            "run_id, started_at, completed_at, mode, files_seen, files_added, "
            "files_updated, files_unchanged, files_deleted, documents_failed, "
            "warning_count, error_count, success, error_summary"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "started_at = excluded.started_at, completed_at = excluded.completed_at, "
            "mode = excluded.mode, files_seen = excluded.files_seen, "
            "files_added = excluded.files_added, files_updated = excluded.files_updated, "
            "files_unchanged = excluded.files_unchanged, "
            "files_deleted = excluded.files_deleted, "
            "documents_failed = excluded.documents_failed, "
            "warning_count = excluded.warning_count, "
            "error_count = excluded.error_count, "
            "success = excluded.success, error_summary = excluded.error_summary",
            (
                run.run_id,
                run.started_at,
                run.completed_at,
                run.mode,
                run.files_seen,
                run.files_added,
                run.files_updated,
                run.files_unchanged,
                run.files_deleted,
                run.documents_failed,
                run.warning_count,
                run.error_count,
                1 if run.success else 0,
                run.error_summary,
            ),
        )

    def _require_open(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("index database is not open")
        return self._conn

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        conn = self._require_open()
        try:
            conn.execute(sql, params)
        except sqlite3.DatabaseError as exc:
            raise CorruptDatabaseError(f"index database error: {exc}")

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        conn = self._require_open()
        try:
            row: sqlite3.Row | None = conn.execute(sql, params).fetchone()
            return row
        except sqlite3.DatabaseError as exc:
            raise CorruptDatabaseError(f"index database error: {exc}")

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        conn = self._require_open()
        try:
            return list(conn.execute(sql, params).fetchall())
        except sqlite3.DatabaseError as exc:
            raise CorruptDatabaseError(f"index database error: {exc}")

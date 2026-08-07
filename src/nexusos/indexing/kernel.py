"""The NexusOS indexing kernel: add, update, remove, search, and candidate lookup.

``IndexKernel`` is the internal API the Phase 2 indexing pipeline builds on.
It composes the workspace-bound SQLite database, deterministic identifiers,
workspace-identity binding, path safety, index-run records, the
exclusive-writer lock, and FTS5-backed full-text search. It deliberately
does NOT implement evidence packets, graph queries, or any public CLI
surface.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator  # noqa: TC003
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from nexusos import __version__
from nexusos.core.errors import (
    IndexEntryError,
    IndexingError,
    WorkspaceMismatchError,
    WorkspaceNotFoundError,
)
from nexusos.core.link_suffixes import LINK_SUFFIXES
from nexusos.core.models import WorkspaceIdentity
from nexusos.core.path_safety import validate_within_workspace
from nexusos.indexing.database import IndexDatabase
from nexusos.indexing.ids import document_id
from nexusos.indexing.lock import IndexLock
from nexusos.indexing.models import (
    DocumentCandidate,
    DocumentSignature,
    IncomingLink,
    IndexCounts,
    IndexedDocument,
    IndexedLink,
    IndexRunRecord,
    RecentDocument,
    SearchHit,
)
from nexusos.indexing.schema import SCHEMA_VERSION
from nexusos.indexing.search import build_fts_query
from nexusos.workspace.init import load_workspace_identity

T = TypeVar("T")


def _normalize_slug(target: str) -> str:
    """Normalize a link target into a forward-slash relative slug.

    Heading fragments (``#...``) and display labels are expected to have been
    separated by the caller before this point.
    """
    slug = target.replace("\\", "/").strip()
    while slug.startswith("./"):
        slug = slug[2:]
    for suffix in LINK_SUFFIXES:
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
            break
    return slug


def _path_stem(normalized_path: str) -> str:
    """Return the filename stem of a normalized path (no directory, no suffix)."""
    name = normalized_path.rsplit("/", 1)[-1]
    for suffix in LINK_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


class IndexKernel:
    """Workspace-bound index kernel with add/update/remove and lookup."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        index_path: Path | None = None,
        identity: WorkspaceIdentity | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root)
        self._identity = identity

        if index_path is not None:
            path = Path(index_path)
            if not path.is_absolute():
                path = self._workspace_root / path
        else:
            path = self._workspace_root / ".nexusos" / "index.sqlite3"
        # The database must stay workspace-bound and pass existing safety checks.
        validate_within_workspace(path, self._workspace_root)
        self._db_path = path
        self._lock_path = self._workspace_root / ".nexusos" / "index.lock"

        self._db = IndexDatabase(self._db_path)
        self._lock = IndexLock(self._lock_path)

    # -- properties -----------------------------------------------------------

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def workspace_id(self) -> str:
        if self._identity is None:
            raise IndexingError("workspace identity is not loaded; call open() first")
        return self._identity.workspace_id

    def index_exists(self) -> bool:
        """Return True when the index database file already exists."""
        return self._db_path.is_file()

    # -- lifecycle ------------------------------------------------------------

    def open(self, *, create_parent: bool = False, read_only: bool = False) -> None:
        """Open the database, migrate it, and bind it to the workspace identity.

        ``create_parent=True`` is required when the state directory does not
        exist yet; it should only be passed when indexing is explicitly invoked
        (never by ``doctor`` or ``status``).

        ``read_only=True`` opens the database with a ``mode=ro`` URI so
        read-only commands (search, browse, status) keep working even when the
        ``.nexusos`` directory is not writable.
        """
        if self._identity is None:
            identity = load_workspace_identity(self._workspace_root)
            if identity is None:
                raise WorkspaceNotFoundError(
                    f"no NexusOS workspace at {self._workspace_root}; run `nexusos init` first",
                    exit_code=2,
                )
            self._identity = identity
        self._db.open(create_parent=create_parent, read_only=read_only)
        try:
            existing = self._db.get_meta("workspace_id")
            if existing is not None and existing != self._identity.workspace_id:
                raise WorkspaceMismatchError(
                    f"index database belongs to workspace {existing!r}, "
                    f"not {self._identity.workspace_id!r}"
                )
            if existing is None:
                self._db.set_meta("workspace_id", self._identity.workspace_id)
                self._db.set_meta("index_schema_version", str(SCHEMA_VERSION))
                self._db.set_meta("application_version", __version__)
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        """Close the database (idempotent)."""
        self._db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run a block inside one write transaction (no nesting)."""
        with self._db.transaction():
            yield

    @contextmanager
    def write_lock(self, *, lock_run_id: str | None = None) -> Iterator[None]:
        """Acquire the exclusive writer lock for the duration of the block."""
        with self._lock.locked(lock_run_id=lock_run_id):
            yield

    # -- document operations --------------------------------------------------

    def add_document(self, doc: IndexedDocument) -> None:
        """Insert a new document entry (raises if the path is already indexed)."""
        self._require_open()
        self._validate_document_identity(doc)
        self._run_in_transaction(lambda: self._db.insert_document(doc))

    def update_document(self, doc: IndexedDocument) -> None:
        """Replace an existing document entry (raises if it is not indexed)."""
        self._require_open()
        self._validate_document_identity(doc)
        self._run_in_transaction(lambda: self._db.replace_document(doc))

    def upsert_document(self, doc: IndexedDocument) -> None:
        """Add or replace a document entry by relative path."""
        self._require_open()
        self._validate_document_identity(doc)
        self._run_in_transaction(lambda: self._db.upsert_document(doc))

    def remove_document(self, relative_path: str) -> bool:
        """Remove a document entry. Returns False when it did not exist."""
        self._require_open()
        return self._run_in_transaction(lambda: self._db.delete_document(relative_path))

    def get_document(self, relative_path: str) -> IndexedDocument | None:
        """Return the stored document entry, or None."""
        self._require_open()
        return self._db.get_document(relative_path)

    def lookup_candidates(self, target: str) -> list[DocumentCandidate]:
        """Return deterministic candidate documents for a wiki-link target.

        Resolution order (mirroring the Phase 2 link rules):
        1. exact normalized-path match (when it exists, it is the only result);
        2. otherwise all documents whose filename stem matches the target stem,
           sorted by ``normalized_path`` then ``title``.

        The caller applies the final resolution state (resolved/unresolved/
        ambiguous); the kernel never chooses arbitrarily between candidates.
        """
        self._require_open()
        slug = _normalize_slug(target)
        # Tier 1: explicit normalized-path match (with or without suffix).
        for candidate_slug in (slug, *(f"{slug}{suffix}" for suffix in LINK_SUFFIXES)):
            exact = self._db.get_candidate_by_normalized_path(candidate_slug)
            if exact is not None:
                return [exact]
        # Tier 2: unique filename stem; all matches are returned in
        # deterministic order and the caller applies the resolution state.
        stem = slug.rsplit("/", 1)[-1]
        return [c for c in self._db.list_documents() if _path_stem(c.normalized_path) == stem]

    # -- status / runs --------------------------------------------------------

    def counts(self) -> IndexCounts:
        """Return row counts for status reporting."""
        self._require_open()
        return self._db.counts()

    # -- search ---------------------------------------------------------------

    def search(
        self,
        term: str,
        *,
        limit: int = 50,
        snippet_tokens: int = 200,
    ) -> list[SearchHit]:
        """Run a ranked full-text search over the indexed corpus.

        ``term`` is a plain user query; it is translated into a safe FTS5
        MATCH expression (prefix matching on every word, case-insensitive).
        Results are ordered by relevance (best first) with deterministic
        tie-breaking, and carry the source file path, line numbers, and an
        excerpt with highlight markers.

        Raises:
            IndexingError: if ``term`` is empty or the query is malformed.
        """
        self._require_open()
        stripped = term.strip()
        if not stripped:
            raise IndexingError("search term must not be empty", exit_code=2)
        query = build_fts_query(stripped)
        return self._db.search_chunks(
            query,
            limit=limit,
            snippet_tokens=snippet_tokens,
        )

    def get_meta(self, key: str) -> str | None:
        self._require_open()
        return self._db.get_meta(key)

    # -- content navigation (read-only lookups) -------------------------------

    def list_documents(self) -> list[DocumentCandidate]:
        """Return all document candidates in deterministic order."""
        self._require_open()
        return self._db.list_documents()

    def list_document_signatures(self) -> list[DocumentSignature]:
        """Return stored mtime/size signatures for all documents (read-only).

        Used by ``get_status`` and lint stale-index to detect content-only
        changes without reading derived rows or file content.
        """
        self._require_open()
        return self._db.list_document_signatures()

    def list_document_links(self) -> list[tuple[str, list[IndexedLink]]]:
        """Return persisted wiki-links grouped by source document (read-only).

        Lightweight variant of full document assembly used by the indexer's
        link-resolution phase, so a no-op incremental pass never reassembles
        unchanged documents (MED-5).
        """
        self._require_open()
        return self._db.list_document_links()

    def get_document_by_id(self, document_id: str) -> IndexedDocument | None:
        """Return a full document by its deterministic identifier, or None."""
        self._require_open()
        return self._db.get_document_by_id(document_id)

    def recent_documents(self, limit: int) -> list[RecentDocument]:
        """Return the ``limit`` most recently modified documents."""
        self._require_open()
        return self._db.list_recent(limit)

    def incoming_links(self, document_id: str) -> list[IncomingLink]:
        """Return links pointing at ``document_id`` with their source paths."""
        self._require_open()
        return self._db.list_incoming_links(document_id)

    def set_meta(self, key: str, value: str) -> None:
        self._require_open()
        self._db.set_meta(key, value)

    def begin_run(self, *, mode: str) -> IndexRunRecord:
        """Start an index run and persist its record."""
        self._require_open()
        return self._db.begin_run(mode=mode)

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
        warnings: list[dict[str, Any]] | None = None,
        error_count: int = 0,
    ) -> IndexRunRecord:
        """Complete an index run, persist counters, and update meta keys."""
        self._require_open()

        def _do() -> IndexRunRecord:
            completed = self._db.complete_run(
                run,
                success=success,
                error_summary=error_summary,
                files_seen=files_seen,
                files_added=files_added,
                files_updated=files_updated,
                files_unchanged=files_unchanged,
                files_deleted=files_deleted,
                documents_failed=documents_failed,
                warning_count=warning_count,
                warnings=warnings,
                error_count=error_count,
            )
            if success:
                self._db.set_meta("last_successful_index_at", completed.completed_at or "")
                self._db.set_meta("last_index_run_id", completed.run_id)
            else:
                self._db.set_meta("last_index_run_id", completed.run_id)
            return completed

        return self._run_in_transaction(_do)

    def get_last_run(self) -> IndexRunRecord | None:
        """Return the most recently started index run, or None."""
        self._require_open()
        return self._db.get_last_run()

    # -- internals ------------------------------------------------------------

    def _require_open(self) -> None:
        if not self._db.is_open:
            raise IndexingError("index kernel is not open; call open() first")

    def _validate_document_identity(self, doc: IndexedDocument) -> None:
        """Enforce the deterministic-ID contract at the kernel boundary."""
        expected = document_id(self.workspace_id, doc.normalized_path)
        if doc.document_id != expected:
            raise IndexEntryError(
                f"document_id {doc.document_id!r} does not match the deterministic id "
                f"{expected!r} for normalized path {doc.normalized_path!r}"
            )

    def _run_in_transaction(self, fn: Callable[[], T]) -> T:
        """Execute ``fn`` inside a transaction, reusing an open one if present."""
        if self._db.in_transaction:
            return fn()
        with self._db.transaction():
            return fn()

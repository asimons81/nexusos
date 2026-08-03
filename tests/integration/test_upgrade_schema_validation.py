"""Integration tests for RC-04: upgrade and schema validation.

Validates the release-candidate upgrade path from ROADMAP RC-04:

- opening an existing ``alpha.2`` workspace with the candidate
- supported schema migration via the ``PRAGMA user_version`` path
- clear refusal of unsupported future schema versions
- derived state delete + rebuild without source loss
- downgrade expectations are documented

The v1 database built here is the schema shipped by the previous published
prerelease train (``SCHEMA_STATEMENTS`` + ``user_version = 1``, before the
v2 ``warnings_json`` migration). The future-schema database uses
``user_version = 99`` to stand in for a schema a newer NexusOS wrote.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from nexusos.core.errors import DatabaseSchemaError
from nexusos.indexing.database import IndexDatabase
from nexusos.indexing.migrations import current_schema_version
from nexusos.indexing.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION
from nexusos.services.status_service import get_status
from nexusos.workspace.init import init_workspace, load_workspace_identity

pytestmark = pytest.mark.integration

_FILES = {
    "wiki/kernel.md": (
        "# Kernel Guide\n\n"
        "The NexusOS indexing kernel provides deterministic identifiers.\n"
        "Search is powered by SQLite FTS5.\n"
    ),
    "wiki/notes.md": "# Notes\n\nNothing about anything relevant here.\n",
}


def _init_with_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    for rel, text in _FILES.items():
        (ws / rel).write_text(text, encoding="utf-8")
    return ws


def _db_path(ws: Path) -> Path:
    return ws / ".nexusos" / "index.sqlite3"


def _set_user_version(ws: Path, version: int) -> None:
    conn = sqlite3.connect(_db_path(ws))
    try:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


def _source_hashes(ws: Path) -> dict[str, str]:
    """SHA-256 of every file in the workspace except derived state (.nexusos)."""
    hashes: dict[str, str] = {}
    for path in sorted(ws.rglob("*")):
        if not path.is_file() or ".nexusos" in path.parts:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[path.relative_to(ws).as_posix()] = digest
    return hashes


def _search_hits(ws: Path, term: str) -> int:
    from nexusos.services.search_service import search_workspace

    return search_workspace(ws, term).total


def test_alpha2_workspace_opens_with_release_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A workspace created and indexed by alpha.2 (schema v2) opens directly
    with the release candidate — no migration required, status is ready."""
    ws = _init_with_corpus(tmp_path, monkeypatch)
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success
    assert current_schema_version(sqlite3.connect(_db_path(ws))) == SCHEMA_VERSION

    # Read-only open (the RC's status/search path) succeeds on the v2 db.
    db = IndexDatabase(_db_path(ws))
    db.open(read_only=True)
    try:
        assert current_schema_version(db._require_open()) == SCHEMA_VERSION
    finally:
        db.close()

    status = get_status(ws)
    assert status["status"] == "ready"
    assert status["index_schema_version"] == SCHEMA_VERSION
    assert _search_hits(ws, "kernel") == 1


def test_v1_workspace_migrates_to_v2_via_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A previous-prerelease (v1) workspace migrates to the candidate schema
    through the documented path: read-only commands refuse with an upgrade
    message, then `nexusos index` migrates via PRAGMA user_version."""
    ws = _init_with_corpus(tmp_path, monkeypatch)
    identity = load_workspace_identity(ws)
    assert identity is not None

    # Build a real v1-schema database, as the previous prerelease shipped.
    state_dir = ws / ".nexusos"
    state_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(_db_path(ws))
    try:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('workspace_id', ?)",
            (identity.workspace_id,),
        )
        conn.commit()
    finally:
        conn.close()
    assert current_schema_version(sqlite3.connect(_db_path(ws))) == 1

    # Read-only commands must refuse with the clear upgrade message, not a
    # misleading permission error.
    db = IndexDatabase(_db_path(ws))
    try:
        with pytest.raises(DatabaseSchemaError, match="run `nexusos index`"):
            db.open(read_only=True)
    finally:
        db.close()

    # The writable index path migrates v1 -> v2 and indexes the corpus.
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success
    conn = sqlite3.connect(_db_path(ws))
    try:
        assert current_schema_version(conn) == 2
        # v2 adds the warnings_json column to index_runs.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(index_runs)")}
    finally:
        conn.close()
    assert "warnings_json" in columns

    status = get_status(ws)
    assert status["status"] == "ready"
    assert _search_hits(ws, "kernel") == 1


def test_future_schema_version_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A database written by a newer NexusOS (future schema) is refused with
    a clear error on both read-only and writable paths."""
    ws = _init_with_corpus(tmp_path, monkeypatch)
    identity = load_workspace_identity(ws)
    assert identity is not None
    state_dir = ws / ".nexusos"
    state_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(_db_path(ws))
    try:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('workspace_id', ?)",
            (identity.workspace_id,),
        )
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
    finally:
        conn.close()

    # Read-only path refuses.
    db = IndexDatabase(_db_path(ws))
    try:
        with pytest.raises(DatabaseSchemaError, match="newer than supported"):
            db.open(read_only=True)
    finally:
        db.close()

    # Writable/index path refuses with the same clear message.
    from nexusos.services.index_service import index_workspace

    with pytest.raises(DatabaseSchemaError, match="newer than supported"):
        index_workspace(ws, full=True)

    # The database is untouched by the refusal.
    assert current_schema_version(sqlite3.connect(_db_path(ws))) == 99


def test_derived_state_delete_and_rebuild_preserves_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting derived index state and reindexing reconstructs it without
    touching a single source byte."""
    ws = _init_with_corpus(tmp_path, monkeypatch)
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success
    assert status_doc_count(ws) == len(_FILES) + 1  # corpus + root README.md
    before = _source_hashes(ws)
    before_db_bytes = _db_path(ws).read_bytes()

    # Delete the derived INDEX state only (the database and its WAL files).
    # workspace.json (workspace identity) is workspace metadata, not index
    # derived state, and must survive so status/search keep working.
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{_db_path(ws)}{suffix}")
        if path.exists():
            path.unlink()
    assert not _db_path(ws).exists()
    assert (ws / ".nexusos" / "workspace.json").exists()

    # Rebuild from source files only.
    run = index_workspace(ws, full=True)
    assert run.success
    assert _db_path(ws).is_file()
    assert status_doc_count(ws) == len(_FILES) + 1
    assert _search_hits(ws, "kernel") == 1

    # Source bytes are byte-for-byte identical.
    after = _source_hashes(ws)
    assert after == before
    # The rebuilt index is a valid, queryable schema-v2 database. It is not
    # required to be byte-identical (timestamps and run ids differ).
    conn = sqlite3.connect(_db_path(ws))
    try:
        assert current_schema_version(conn) == SCHEMA_VERSION
    finally:
        conn.close()
    assert _db_path(ws).read_bytes() != before_db_bytes


def test_nuclear_nexusos_delete_recoverable_via_adopt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even deleting the entire .nexusos directory (identity included) never
    loses source files: re-initializing with --adopt restores the workspace
    and a fresh index reconstructs all derived state."""
    ws = _init_with_corpus(tmp_path, monkeypatch)
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success
    before = _source_hashes(ws)

    # Remove all derived state and workspace metadata.
    state_dir = ws / ".nexusos"
    assert state_dir.is_dir()
    for path in sorted(state_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    state_dir.rmdir()
    assert not state_dir.exists()
    assert (ws / "wiki" / "kernel.md").exists()  # sources untouched

    # Adopt the existing directory back as a workspace and reindex.
    init_workspace(ws, template="blank", adopt=True)
    run = index_workspace(ws, full=True)
    assert run.success
    assert _db_path(ws).is_file()
    assert status_doc_count(ws) == len(_FILES) + 1
    assert _search_hits(ws, "kernel") == 1

    after = _source_hashes(ws)
    assert after == before


def test_downgrade_expectations_documented(tmp_path: Path) -> None:
    """The release procedure must state that schema downgrades are not
    implemented, so operators never assume a safe downgrade path exists."""
    repo_root = Path(__file__).resolve().parents[2]
    releasing = (repo_root / "docs" / "releasing.md").read_text(encoding="utf-8")
    normalized = " ".join(releasing.split())
    assert "downgrade" in normalized.lower()
    assert "must never imply that a schema downgrade is safe" in normalized


def status_doc_count(ws: Path) -> int:
    status = get_status(ws)
    assert status["status"] == "ready"
    return int(status["document_count"])

"""Focused unit tests for the NexusOS indexing kernel API."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path  # noqa: TC003

import pytest

from nexusos.core.errors import (
    CorruptDatabaseError,
    DatabaseError,
    DatabaseSchemaError,
    IndexEntryError,
    IndexEntryExistsError,
    IndexEntryNotFoundError,
    IndexTransactionError,
    WorkspaceMismatchError,
    WorkspaceNotFoundError,
)
from nexusos.core.models import WorkspaceIdentity
from nexusos.indexing.ids import chunk_id, document_id
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import (
    IndexedChunk,
    IndexedDocument,
    IndexedHeading,
    IndexedLink,
)
from nexusos.indexing.schema import SCHEMA_VERSION

_WS_A = "nxo_ws_kernel_a"
_WS_B = "nxo_ws_kernel_b"


def _identity(workspace_id: str = _WS_A) -> WorkspaceIdentity:
    return WorkspaceIdentity(
        workspace_id=workspace_id,
        created_at="2026-01-01T00:00:00Z",
        nexusos_version="0.1.0",
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _make_doc(
    workspace_id: str,
    relative_path: str,
    *,
    title: str | None = None,
    headings: list[IndexedHeading] | None = None,
    chunks: list[IndexedChunk] | None = None,
    wikilinks: list[IndexedLink] | None = None,
    tags: list[str] | None = None,
) -> IndexedDocument:
    normalized_path = relative_path.replace("\\", "/")
    doc_id = document_id(workspace_id, normalized_path)
    heading_text = title or "Alpha"
    if headings is None:
        headings = [
            IndexedHeading(
                ordinal=1,
                level=1,
                text=heading_text,
                normalized_text=heading_text.lower(),
                line=1,
            )
        ]
    if chunks is None:
        body = f"{heading_text} body text"
        body_sha = _sha(body)
        chunks = [
            IndexedChunk(
                chunk_id=chunk_id(doc_id, 1, body_sha),
                document_id=doc_id,
                ordinal=1,
                heading_path=(heading_text,),
                start_line=1,
                end_line=2,
                text=body,
                content_sha256=body_sha,
            )
        ]
    return IndexedDocument(
        document_id=doc_id,
        relative_path=normalized_path,
        normalized_path=normalized_path,
        collection="wiki",
        title=heading_text,
        file_type="markdown",
        authority_class="unknown",
        mtime_ns=1_700_000_000_000_000_000,
        size_bytes=100,
        content_sha256=_sha("content"),
        frontmatter_json="{}",
        indexed_at="2026-01-01T00:00:00+00:00",
        line_count=3,
        headings=headings,
        chunks=chunks,
        wikilinks=wikilinks or [],
        tags=tags or [],
    )


@pytest.fixture
def kernel(tmp_path: Path) -> Iterator[IndexKernel]:
    k = IndexKernel(tmp_path, identity=_identity())
    k.open(create_parent=True)
    try:
        yield k
    finally:
        k.close()


def test_open_creates_schema_and_meta(kernel: IndexKernel, tmp_path: Path) -> None:
    assert kernel.index_exists()
    assert kernel.get_meta("workspace_id") == _WS_A
    assert kernel.get_meta("index_schema_version") == str(SCHEMA_VERSION)
    assert kernel.get_meta("application_version") is not None
    counts = kernel.counts()
    assert counts.document_count == 0
    assert counts.chunk_count == 0
    assert counts.heading_count == 0
    assert counts.resolved_link_count == 0


def test_open_refuses_to_create_missing_state_dir(tmp_path: Path) -> None:
    k = IndexKernel(tmp_path, identity=_identity())
    with pytest.raises(DatabaseError):
        k.open()  # create_parent defaults to False
    assert not k.index_exists()


def test_open_requires_workspace_identity(tmp_path: Path) -> None:
    k = IndexKernel(tmp_path)  # no identity, no workspace.json
    with pytest.raises(WorkspaceNotFoundError):
        k.open(create_parent=True)


def test_open_rejects_db_outside_workspace(tmp_path: Path) -> None:
    from nexusos.core.errors import PathSafetyError

    outside = tmp_path.parent / "outside.sqlite3"
    with pytest.raises(PathSafetyError):
        IndexKernel(tmp_path, index_path=outside, identity=_identity())


def test_add_and_get_roundtrip(kernel: IndexKernel) -> None:
    doc = _make_doc(_WS_A, "wiki/alpha.md")
    kernel.add_document(doc)
    got = kernel.get_document("wiki/alpha.md")
    assert got == doc
    counts = kernel.counts()
    assert counts.document_count == 1
    assert counts.chunk_count == 1
    assert counts.heading_count == 1


def test_add_duplicate_raises(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    with pytest.raises(IndexEntryExistsError):
        kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))


def test_update_replaces_rows(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    updated = _make_doc(_WS_A, "wiki/alpha.md", title="Beta")
    kernel.update_document(updated)
    got = kernel.get_document("wiki/alpha.md")
    assert got is not None
    assert got.title == "Beta"
    assert got.document_id == document_id(_WS_A, "wiki/alpha.md")  # identity stable
    counts = kernel.counts()
    assert counts.document_count == 1
    assert counts.chunk_count == 1


def test_update_missing_raises(kernel: IndexKernel) -> None:
    with pytest.raises(IndexEntryNotFoundError):
        kernel.update_document(_make_doc(_WS_A, "wiki/absent.md"))


def test_remove_and_remove_again(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    assert kernel.remove_document("wiki/alpha.md") is True
    assert kernel.get_document("wiki/alpha.md") is None
    assert kernel.remove_document("wiki/alpha.md") is False
    counts = kernel.counts()
    assert counts.document_count == 0
    assert counts.chunk_count == 0


def test_upsert_adds_then_replaces(kernel: IndexKernel) -> None:
    kernel.upsert_document(_make_doc(_WS_A, "wiki/alpha.md"))
    kernel.upsert_document(_make_doc(_WS_A, "wiki/alpha.md", title="Beta"))
    got = kernel.get_document("wiki/alpha.md")
    assert got is not None
    assert got.title == "Beta"
    assert kernel.counts().document_count == 1


def test_remove_resets_incoming_links(kernel: IndexKernel) -> None:
    target_id = document_id(_WS_A, "wiki/target.md")
    kernel.add_document(_make_doc(_WS_A, "wiki/target.md", title="Target"))
    kernel.add_document(
        _make_doc(
            _WS_A,
            "wiki/source.md",
            wikilinks=[
                IndexedLink(
                    source_line=3,
                    raw_target="target",
                    target_slug="target",
                    target_document_id=target_id,
                    resolved=True,
                    resolution_state="resolved",
                )
            ],
        )
    )
    assert kernel.counts().resolved_link_count == 1
    assert kernel.remove_document("wiki/target.md") is True
    counts = kernel.counts()
    assert counts.document_count == 1
    assert counts.resolved_link_count == 0
    assert counts.unresolved_link_count == 1
    source = kernel.get_document("wiki/source.md")
    assert source is not None
    link = source.wikilinks[0]
    assert link.target_document_id is None
    assert link.resolved is False
    assert link.resolution_state == "unresolved"


def test_lookup_exact_path_wins(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    kernel.add_document(_make_doc(_WS_A, "journal/alpha.md"))
    candidates = kernel.lookup_candidates("wiki/alpha")
    assert [c.normalized_path for c in candidates] == ["wiki/alpha.md"]


def test_lookup_strips_extension(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    candidates = kernel.lookup_candidates("wiki/alpha.md")
    assert [c.normalized_path for c in candidates] == ["wiki/alpha.md"]


def test_lookup_stem_matches_all_in_deterministic_order(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    kernel.add_document(_make_doc(_WS_A, "journal/alpha.md"))
    candidates = kernel.lookup_candidates("alpha")
    assert [c.normalized_path for c in candidates] == ["journal/alpha.md", "wiki/alpha.md"]


def test_lookup_empty_when_no_match(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    assert kernel.lookup_candidates("missing") == []
    assert kernel.lookup_candidates("wiki/missing") == []


def test_lookup_consistent_across_calls(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/beta.md"))
    kernel.add_document(_make_doc(_WS_A, "raw/beta.md"))
    kernel.add_document(_make_doc(_WS_A, "mocs/beta.md"))
    first = [c.normalized_path for c in kernel.lookup_candidates("beta")]
    second = [c.normalized_path for c in kernel.lookup_candidates("beta")]
    assert first == second == ["mocs/beta.md", "raw/beta.md", "wiki/beta.md"]


def test_deterministic_id_enforced(kernel: IndexKernel) -> None:
    wrong = _make_doc(_WS_A, "wiki/alpha.md").model_copy(
        update={"document_id": document_id(_WS_A, "wiki/other.md")}
    )
    with pytest.raises(IndexEntryError):
        kernel.add_document(wrong)


def test_workspace_mismatch_rejected(tmp_path: Path) -> None:
    first = IndexKernel(tmp_path, identity=_identity(_WS_A))
    first.open(create_parent=True)
    first.close()
    second = IndexKernel(tmp_path, identity=_identity(_WS_B))
    with pytest.raises(WorkspaceMismatchError):
        second.open()


def test_future_schema_version_refused(tmp_path: Path) -> None:
    k = IndexKernel(tmp_path, identity=_identity())
    k.open(create_parent=True)
    k.close()
    conn = sqlite3.connect(str(tmp_path / ".nexusos" / "index.sqlite3"))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    again = IndexKernel(tmp_path, identity=_identity())
    with pytest.raises(DatabaseSchemaError):
        again.open()


def test_corrupt_database_rejected(tmp_path: Path) -> None:
    (tmp_path / ".nexusos").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".nexusos" / "index.sqlite3").write_bytes(b"this is not a sqlite database")
    k = IndexKernel(tmp_path, identity=_identity())
    with pytest.raises(CorruptDatabaseError):
        k.open()


def test_transaction_rollback(kernel: IndexKernel) -> None:
    with pytest.raises(RuntimeError), kernel.transaction():  # noqa: PT012
        kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
        raise RuntimeError("boom")
    assert kernel.get_document("wiki/alpha.md") is None
    assert kernel.counts().document_count == 0


def test_nested_transaction_rejected(kernel: IndexKernel) -> None:
    with pytest.raises(IndexTransactionError), kernel.transaction(), kernel.transaction():
        pass


def test_batch_transaction_is_atomic(kernel: IndexKernel) -> None:
    with kernel.transaction():
        kernel.add_document(_make_doc(_WS_A, "wiki/a.md"))
        kernel.add_document(_make_doc(_WS_A, "wiki/b.md"))
    assert kernel.counts().document_count == 2


def test_run_records(kernel: IndexKernel) -> None:
    assert kernel.get_last_run() is None
    run = kernel.begin_run(mode="incremental")
    assert run.run_id.startswith("nxo_run_")
    completed = kernel.complete_run(
        run, success=True, files_seen=3, files_added=2, files_unchanged=1
    )
    assert completed.completed_at is not None
    last = kernel.get_last_run()
    assert last is not None
    assert last.run_id == run.run_id
    assert last.success is True
    assert last.files_seen == 3
    assert last.files_added == 2
    assert kernel.get_meta("last_successful_index_at") == completed.completed_at
    assert kernel.get_meta("last_index_run_id") == run.run_id


def test_failed_run_keeps_last_success(kernel: IndexKernel) -> None:
    ok = kernel.complete_run(kernel.begin_run(mode="incremental"), success=True)
    failed = kernel.complete_run(
        kernel.begin_run(mode="incremental"),
        success=False,
        error_summary="parse failure",
        documents_failed=1,
    )
    assert failed.success is False
    last = kernel.get_last_run()
    assert last is not None
    assert last.run_id == failed.run_id
    # The last successful timestamp is preserved from the earlier success.
    assert kernel.get_meta("last_successful_index_at") == ok.completed_at


def test_fts_rows_stay_consistent_with_chunks(kernel: IndexKernel, tmp_path: Path) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md", tags=["agents", "memory"]))
    kernel.close()
    conn = sqlite3.connect(str(tmp_path / ".nexusos" / "index.sqlite3"))
    chunk_count = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    fts_count = int(conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0])
    conn.close()
    assert chunk_count == 1
    assert fts_count == chunk_count


def test_no_absolute_paths_stored(kernel: IndexKernel, tmp_path: Path) -> None:
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    kernel.close()
    conn = sqlite3.connect(str(tmp_path / ".nexusos" / "index.sqlite3"))
    rows = conn.execute("SELECT relative_path, normalized_path FROM documents").fetchall()
    conn.close()
    assert rows
    for relative_path, normalized_path in rows:
        assert str(tmp_path) not in relative_path
        assert str(tmp_path) not in normalized_path
        assert not relative_path.startswith("/")


def test_meta_roundtrip(kernel: IndexKernel) -> None:
    assert kernel.get_meta("nonexistent") is None
    kernel.set_meta("config_fingerprint", "abc123")
    assert kernel.get_meta("config_fingerprint") == "abc123"


def test_database_is_reconstructible(kernel: IndexKernel, tmp_path: Path) -> None:
    """Deleting the DB and reindexing must fully reconstruct the index."""
    kernel.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
    assert kernel.get_document("wiki/alpha.md") is not None
    kernel.close()
    db_path = tmp_path / ".nexusos" / "index.sqlite3"
    db_path.unlink()
    fresh = IndexKernel(tmp_path, identity=_identity())
    fresh.open(create_parent=True)
    try:
        assert fresh.counts().document_count == 0
        assert fresh.get_document("wiki/alpha.md") is None
        fresh.add_document(_make_doc(_WS_A, "wiki/alpha.md"))
        assert fresh.get_document("wiki/alpha.md") is not None
    finally:
        fresh.close()

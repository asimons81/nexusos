"""Acceptance/regression tests for the NexusOS indexing kernel.

These tests verify the kernel's round-trip behavior, empty-index behavior,
deterministic candidate lookup edge cases, invalid-input/error paths, and the
safety invariants captured in ``PHASE2_BASELINE.md`` (source immutability,
identity binding through a real workspace, disposable index). They complement
the focused unit tests in ``test_index_kernel.py`` without weakening them.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path  # noqa: TC003

import pytest

from nexusos.core.errors import IndexingError
from nexusos.core.models import WorkspaceIdentity
from nexusos.indexing.ids import chunk_id, document_id
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import (
    IndexedChunk,
    IndexedDocument,
    IndexedHeading,
    IndexedLink,
)
from nexusos.workspace.init import init_workspace, load_workspace_identity

_WS = "nxo_ws_acceptance"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _identity(workspace_id: str = _WS) -> WorkspaceIdentity:
    return WorkspaceIdentity(
        workspace_id=workspace_id,
        created_at="2026-01-01T00:00:00Z",
        nexusos_version="0.1.0",
    )


def _make_doc(
    workspace_id: str,
    relative_path: str,
    *,
    title: str | None = None,
    body: str | None = None,
    wikilinks: list[IndexedLink] | None = None,
) -> IndexedDocument:
    normalized_path = relative_path.replace("\\", "/")
    doc_id = document_id(workspace_id, normalized_path)
    heading_text = title or "Alpha"
    body_text = body or f"{heading_text} body text"
    body_sha = _sha(body_text)
    chunk = IndexedChunk(
        chunk_id=chunk_id(doc_id, 1, body_sha),
        document_id=doc_id,
        ordinal=1,
        heading_path=(heading_text,),
        start_line=1,
        end_line=2,
        text=body_text,
        content_sha256=body_sha,
    )
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
        headings=[
            IndexedHeading(
                ordinal=1,
                level=1,
                text=heading_text,
                normalized_text=heading_text.lower(),
                line=1,
            )
        ],
        chunks=[chunk],
        wikilinks=wikilinks or [],
        tags=[],
    )


def _two_chunk_doc(
    workspace_id: str,
    relative_path: str,
    *,
    body_a: str = "first chunk",
    body_b: str = "second chunk",
) -> IndexedDocument:
    normalized_path = relative_path.replace("\\", "/")
    doc_id = document_id(workspace_id, normalized_path)
    heading_text = "Alpha"
    chunks = [
        IndexedChunk(
            chunk_id=chunk_id(doc_id, 1, _sha(body_a)),
            document_id=doc_id,
            ordinal=1,
            heading_path=(heading_text,),
            start_line=1,
            end_line=1,
            text=body_a,
            content_sha256=_sha(body_a),
        ),
        IndexedChunk(
            chunk_id=chunk_id(doc_id, 2, _sha(body_b)),
            document_id=doc_id,
            ordinal=2,
            heading_path=(heading_text,),
            start_line=2,
            end_line=2,
            text=body_b,
            content_sha256=_sha(body_b),
        ),
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
        headings=[
            IndexedHeading(
                ordinal=1,
                level=1,
                text=heading_text,
                normalized_text=heading_text.lower(),
                line=1,
            )
        ],
        chunks=chunks,
        wikilinks=[],
        tags=[],
    )


@pytest.fixture
def kernel(tmp_path: Path) -> Iterator[IndexKernel]:
    k = IndexKernel(tmp_path, identity=_identity())
    k.open(create_parent=True)
    try:
        yield k
    finally:
        k.close()


# -- round-trip behavior ------------------------------------------------------


def test_full_lifecycle_roundtrip(kernel: IndexKernel) -> None:
    v1 = _make_doc(_WS, "wiki/alpha.md")
    kernel.add_document(v1)
    assert kernel.counts().document_count == 1
    assert [c.normalized_path for c in kernel.lookup_candidates("alpha")] == ["wiki/alpha.md"]

    v2 = _make_doc(_WS, "wiki/alpha.md", title="Alpha v2", body="totally different body")
    kernel.update_document(v2)
    got = kernel.get_document("wiki/alpha.md")
    assert got is not None
    assert got.title == "Alpha v2"
    assert got.document_id == v1.document_id  # identity stable across content change
    assert got.chunks[0].chunk_id != v1.chunks[0].chunk_id  # chunk id rotated
    assert kernel.counts().document_count == 1

    assert kernel.remove_document("wiki/alpha.md") is True
    assert kernel.get_document("wiki/alpha.md") is None
    assert kernel.counts().document_count == 0


def test_update_shrinking_chunks_removes_stale_rows(kernel: IndexKernel, tmp_path: Path) -> None:
    """Updating a document with fewer chunks must not leave stale rows behind."""
    kernel.add_document(_two_chunk_doc(_WS, "wiki/alpha.md"))
    assert kernel.counts().chunk_count == 2
    kernel.update_document(_make_doc(_WS, "wiki/alpha.md", body="one chunk now"))
    assert kernel.counts().chunk_count == 1
    kernel.close()
    conn = sqlite3.connect(str(tmp_path / ".nexusos" / "index.sqlite3"))
    chunk_rows = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    fts_rows = int(conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0])
    conn.close()
    assert chunk_rows == 1
    assert fts_rows == 1


def test_remove_clears_all_derived_rows(kernel: IndexKernel, tmp_path: Path) -> None:
    """Removing a document must clear documents, chunks, headings, links, and FTS."""
    kernel.add_document(_two_chunk_doc(_WS, "wiki/alpha.md"))
    assert kernel.remove_document("wiki/alpha.md") is True
    kernel.close()
    conn = sqlite3.connect(str(tmp_path / ".nexusos" / "index.sqlite3"))
    for table in ("documents", "chunks", "headings", "links", "chunks_fts"):
        count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        assert count == 0, f"{table} should be empty after remove, got {count}"
    conn.close()


# -- empty-index behavior -----------------------------------------------------


def test_empty_index_behaviors(kernel: IndexKernel) -> None:
    assert kernel.get_document("wiki/alpha.md") is None
    assert kernel.remove_document("wiki/alpha.md") is False
    assert kernel.lookup_candidates("alpha") == []
    assert kernel.lookup_candidates("wiki/alpha.md") == []
    counts = kernel.counts()
    assert counts.document_count == 0
    assert counts.chunk_count == 0
    assert counts.heading_count == 0
    assert counts.resolved_link_count == 0
    assert counts.unresolved_link_count == 0
    assert kernel.get_last_run() is None


# -- invalid-input / error paths ----------------------------------------------


def test_kernel_operations_require_open(tmp_path: Path) -> None:
    k = IndexKernel(tmp_path, identity=_identity())
    doc = _make_doc(_WS, "wiki/alpha.md")
    with pytest.raises(IndexingError):
        k.add_document(doc)
    with pytest.raises(IndexingError):
        k.update_document(doc)
    with pytest.raises(IndexingError):
        k.remove_document("wiki/alpha.md")
    with pytest.raises(IndexingError):
        k.get_document("wiki/alpha.md")
    with pytest.raises(IndexingError):
        k.lookup_candidates("alpha")
    with pytest.raises(IndexingError):
        k.counts()
    with pytest.raises(IndexingError):
        k.get_meta("workspace_id")
    with pytest.raises(IndexingError):
        k.begin_run(mode="full")
    # Constructing the kernel must not create state.
    assert not (tmp_path / ".nexusos" / "index.sqlite3").exists()


def test_workspace_id_requires_loaded_identity(tmp_path: Path) -> None:
    k = IndexKernel(tmp_path)
    with pytest.raises(IndexingError):
        _ = k.workspace_id


# -- deterministic candidate lookup edge cases --------------------------------


def test_lookup_normalizes_backslash_and_dot_prefix(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS, "wiki/alpha.md"))
    assert [c.normalized_path for c in kernel.lookup_candidates("wiki\\alpha")] == ["wiki/alpha.md"]
    assert [c.normalized_path for c in kernel.lookup_candidates("./wiki/alpha")] == [
        "wiki/alpha.md"
    ]


def test_lookup_suffix_variants(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS, "wiki/alpha.md"))
    for target in ("alpha.md", "alpha.markdown", "alpha.txt", "wiki/alpha.md"):
        assert [c.normalized_path for c in kernel.lookup_candidates(target)] == ["wiki/alpha.md"], (
            target
        )


def test_lookup_empty_target_is_empty(kernel: IndexKernel) -> None:
    kernel.add_document(_make_doc(_WS, "wiki/alpha.md"))
    assert kernel.lookup_candidates("") == []


def test_deterministic_lookup_across_reopen(tmp_path: Path) -> None:
    """Candidate order must be identical after close/reopen (persistence)."""
    k = IndexKernel(tmp_path, identity=_identity())
    k.open(create_parent=True)
    for path in ("wiki/beta.md", "raw/beta.md", "mocs/beta.md"):
        k.add_document(_make_doc(_WS, path))
    before = [c.normalized_path for c in k.lookup_candidates("beta")]
    k.close()

    again = IndexKernel(tmp_path, identity=_identity())
    again.open()
    try:
        after = [c.normalized_path for c in again.lookup_candidates("beta")]
    finally:
        again.close()
    assert before == after == ["mocs/beta.md", "raw/beta.md", "wiki/beta.md"]


# -- safety invariants from PHASE2_BASELINE.md --------------------------------


def test_update_preserves_incoming_links(kernel: IndexKernel) -> None:
    """Replacing a document must not touch links that point at it."""
    target_id = document_id(_WS, "wiki/target.md")
    kernel.add_document(_make_doc(_WS, "wiki/target.md", title="Target"))
    kernel.add_document(
        _make_doc(
            _WS,
            "wiki/source.md",
            title="Source",
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
    kernel.update_document(_make_doc(_WS, "wiki/target.md", title="Target v2"))
    source = kernel.get_document("wiki/source.md")
    assert source is not None
    link = source.wikilinks[0]
    assert link.target_document_id == target_id
    assert link.resolved is True
    assert link.resolution_state == "resolved"
    assert kernel.counts().resolved_link_count == 1


def test_identity_loaded_from_real_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kernel must bind to the identity persisted by a real `nexusos init`."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    identity = load_workspace_identity(ws)
    assert identity is not None

    k = IndexKernel(ws)
    k.open(create_parent=True)
    try:
        assert k.workspace_id == identity.workspace_id
        assert k.get_meta("workspace_id") == identity.workspace_id
        assert k.db_path == ws / ".nexusos" / "index.sqlite3"
        assert k.index_exists()
    finally:
        k.close()


def test_source_files_untouched_by_kernel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kernel add/update/remove must never mutate source documents."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="starter")
    source = ws / "wiki" / "alpha.md"
    source.write_text("# Alpha\n\nbody\n", encoding="utf-8")
    original = source.read_bytes()

    identity = load_workspace_identity(ws)
    assert identity is not None
    k = IndexKernel(ws)
    k.open(create_parent=True)
    try:
        k.add_document(_make_doc(identity.workspace_id, "wiki/alpha.md"))
        k.update_document(
            _make_doc(
                identity.workspace_id,
                "wiki/alpha.md",
                title="Changed",
                body="changed body",
            )
        )
        k.remove_document("wiki/alpha.md")
    finally:
        k.close()
    assert source.read_bytes() == original

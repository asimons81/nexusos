"""Unit tests for the NexusOS content-navigation service layer.

Covers the five Phase 3 navigation operations (browse, read, recent, links,
context) against a real workspace identity with kernel-seeded documents:
happy paths, error paths (unknown/ambiguous items, empty index, invalid
limits), and the read-only invariant (navigation never creates the index
database).
"""

from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003

import pytest

from nexusos.core.errors import (
    AmbiguousDocumentError,
    DocumentNotFoundError,
    IndexingError,
    NavigationError,
    WorkspaceNotFoundError,
)
from nexusos.indexing.ids import chunk_id, document_id
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import (
    IndexedChunk,
    IndexedDocument,
    IndexedHeading,
    IndexedLink,
)
from nexusos.services import navigation_service as nav
from nexusos.workspace.init import init_workspace, load_workspace_identity

_WS = "nxo_ws_navigation_unit"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _make_doc(
    workspace_id: str,
    relative_path: str,
    *,
    title: str | None = None,
    body: str | None = None,
    wikilinks: list[IndexedLink] | None = None,
    mtime_ns: int = 1_700_000_000_000_000_000,
    collection: str = "wiki",
    headings: list[tuple[int, str]] | None = None,
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
    if headings is None:
        headings = [(1, heading_text)]
    return IndexedDocument(
        document_id=doc_id,
        relative_path=normalized_path,
        normalized_path=normalized_path,
        collection=collection,
        title=heading_text,
        file_type="markdown",
        authority_class="unknown",
        mtime_ns=mtime_ns,
        size_bytes=100,
        content_sha256=_sha("content"),
        frontmatter_json="{}",
        indexed_at="2026-01-01T00:00:00+00:00",
        line_count=3,
        headings=[
            IndexedHeading(
                ordinal=i,
                level=level,
                text=text,
                normalized_text=text.lower(),
                line=i,
            )
            for i, (level, text) in enumerate(headings, start=1)
        ],
        chunks=[chunk],
        wikilinks=wikilinks or [],
        tags=[],
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real blank workspace with a seeded index (3 documents + links)."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    identity = load_workspace_identity(ws)
    assert identity is not None
    ws_id = identity.workspace_id

    target_id = document_id(ws_id, "wiki/target.md")
    kernel = IndexKernel(ws)
    kernel.open(create_parent=True)
    try:
        kernel.add_document(
            _make_doc(
                ws_id,
                "wiki/target.md",
                title="Target",
                mtime_ns=1_700_000_000_000_000_000,
            )
        )
        kernel.add_document(
            _make_doc(
                ws_id,
                "wiki/source.md",
                title="Source",
                mtime_ns=1_700_000_000_000_100_000,
                wikilinks=[
                    IndexedLink(
                        source_line=3,
                        raw_target="target",
                        target_slug="target",
                        target_document_id=target_id,
                        resolved=True,
                        resolution_state="resolved",
                    ),
                    IndexedLink(
                        source_line=5,
                        raw_target="missing",
                        target_slug="missing",
                        target_document_id=None,
                        resolved=False,
                        resolution_state="unresolved",
                    ),
                ],
            )
        )
        kernel.add_document(
            _make_doc(
                ws_id,
                "journal/note.md",
                title="Note",
                collection="journal",
                mtime_ns=1_700_000_000_000_200_000,
            )
        )
    finally:
        kernel.close()
    return ws


def test_browse_lists_all_documents(workspace: Path) -> None:
    data = nav.browse_workspace(workspace)
    paths = [d["path"] for d in data["documents"]]
    assert paths == ["journal/note.md", "wiki/source.md", "wiki/target.md"]
    assert data["count"] == 3


def test_browse_filters_by_collection(workspace: Path) -> None:
    data = nav.browse_workspace(workspace, collection="wiki")
    paths = [d["path"] for d in data["documents"]]
    assert paths == ["wiki/source.md", "wiki/target.md"]
    assert data["count"] == 2


def test_browse_unknown_collection_is_empty(workspace: Path) -> None:
    data = nav.browse_workspace(workspace, collection="nonexistent")
    assert data["count"] == 0
    assert data["documents"] == []


def test_browse_respects_limit(workspace: Path) -> None:
    data = nav.browse_workspace(workspace, limit=1)
    assert data["count"] == 1


def test_read_by_path_returns_content_and_path(workspace: Path) -> None:
    data = nav.read_document(workspace, "wiki/target.md")
    assert data["path"] == "wiki/target.md"
    assert data["title"] == "Target"
    assert data["content"] == "Target body text"


def test_read_by_stem_resolves_unique(workspace: Path) -> None:
    data = nav.read_document(workspace, "target")
    assert data["path"] == "wiki/target.md"


def test_read_by_document_id(workspace: Path) -> None:
    kernel = nav._open_readonly(workspace)
    try:
        doc = kernel.get_document_by_id(document_id(kernel.workspace_id, "wiki/target.md"))
        assert doc is not None
    finally:
        kernel.close()
    assert doc is not None
    data = nav.read_document(workspace, doc.document_id)
    assert data["path"] == "wiki/target.md"


def test_read_unknown_item_raises(workspace: Path) -> None:
    with pytest.raises(DocumentNotFoundError):
        nav.read_document(workspace, "does-not-exist")


def test_read_ambiguous_item_raises(workspace: Path) -> None:
    # journal/note.md and wiki/target.md do not share a stem; add a clash.
    kernel = nav._open_readonly(workspace)
    try:
        ws_id = kernel.workspace_id
        kernel.add_document(_make_doc(ws_id, "raw/note.md", title="Raw Note", collection="raw"))
    finally:
        kernel.close()
    with pytest.raises(AmbiguousDocumentError):
        nav.read_document(workspace, "note")


def test_read_empty_item_raises(workspace: Path) -> None:
    with pytest.raises(DocumentNotFoundError):
        nav.read_document(workspace, "   ")


def test_read_max_lines_and_max_chars(workspace: Path) -> None:
    data = nav.read_document(workspace, "wiki/target.md", max_chars=5)
    assert data["content"] == "Targe"
    assert data["truncated"] is True


def test_recent_orders_newest_first(workspace: Path) -> None:
    data = nav.recent_documents(workspace, limit=3)
    paths = [d["path"] for d in data["documents"]]
    assert paths == ["journal/note.md", "wiki/source.md", "wiki/target.md"]
    assert data["documents"][0]["mtime"].endswith("+00:00")


def test_recent_respects_limit(workspace: Path) -> None:
    data = nav.recent_documents(workspace, limit=1)
    assert data["count"] == 1
    assert data["documents"][0]["path"] == "journal/note.md"


def test_recent_rejects_non_positive_limit(workspace: Path) -> None:
    with pytest.raises(NavigationError):
        nav.recent_documents(workspace, limit=0)


def test_links_shows_outgoing_and_incoming(workspace: Path) -> None:
    target = nav.document_links(workspace, "wiki/target.md")
    assert target["path"] == "wiki/target.md"
    assert target["incoming"][0]["source_path"] == "wiki/source.md"
    assert target["incoming"][0]["resolution_state"] == "resolved"

    source = nav.document_links(workspace, "wiki/source.md")
    states = {link["raw_target"]: link["resolution_state"] for link in source["outgoing"]}
    assert states == {"target": "resolved", "missing": "unresolved"}
    # Resolved outgoing link carries the target path.
    by_target = {link["raw_target"]: link for link in source["outgoing"]}
    assert by_target["target"]["target_path"] == "wiki/target.md"


def test_links_unknown_item_raises(workspace: Path) -> None:
    with pytest.raises(DocumentNotFoundError):
        nav.document_links(workspace, "nope")


def test_context_shows_siblings_and_linked(workspace: Path) -> None:
    data = nav.document_context(workspace, "wiki/target.md")
    assert data["path"] == "wiki/target.md"
    # Siblings: same collection (wiki), excluding self.
    sibling_paths = [s["path"] for s in data["siblings"]]
    assert sibling_paths == ["wiki/source.md"]
    # Linked: source.md points at target, so it is a linked document.
    assert "wiki/source.md" in data["linked"]
    # Headings are included.
    assert data["headings"][0]["text"] == "Target"


def test_context_unknown_item_raises(workspace: Path) -> None:
    with pytest.raises(DocumentNotFoundError):
        nav.document_context(workspace, "missing")


def test_no_workspace_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(WorkspaceNotFoundError):
        nav.browse_workspace(empty)


def test_unindexed_workspace_raises_without_creating_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PHASE2 invariant: read-only navigation must never create the index DB."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    with pytest.raises(IndexingError):
        nav.browse_workspace(ws)
    assert not (ws / ".nexusos" / "index.sqlite3").exists()
    assert not (ws / ".nexusos" / "index.lock").exists()

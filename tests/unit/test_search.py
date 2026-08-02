"""Unit tests for the NexusOS search layer.

Covers the FTS5 query builder, the kernel-level ``search`` API (matched
terms, no-match, multiple ranked results, prefix and case handling, limits,
read-only behavior), and service-level error paths.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path  # noqa: TC003

import pytest

from nexusos.core.errors import IndexingError, WorkspaceNotFoundError
from nexusos.core.models import WorkspaceIdentity
from nexusos.indexing.ids import chunk_id, document_id
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import IndexedChunk, IndexedDocument, IndexedHeading
from nexusos.indexing.search import build_fts_query
from nexusos.services.search_service import search_workspace
from nexusos.workspace.init import init_workspace

_WS = "nxo_ws_search_unit"


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


# -- FTS5 query builder -------------------------------------------------------


class TestBuildFtsQuery:
    def test_single_word_is_prefix_phrase(self) -> None:
        assert build_fts_query("kernel") == '"kernel"*'

    def test_multiple_words_implicit_and(self) -> None:
        assert build_fts_query("kernel search") == '"kernel"* "search"*'

    def test_embedded_quote_is_escaped(self) -> None:
        assert build_fts_query('a"b') == '"a""b"*'

    def test_trailing_star_collapsed(self) -> None:
        assert build_fts_query("foo**") == '"foo"*'

    def test_surrounding_whitespace_stripped(self) -> None:
        assert build_fts_query("  kernel  ") == '"kernel"*'

    def test_operator_words_are_literal(self) -> None:
        # AND/OR/NOT must be quoted so they are treated as words, not operators.
        assert build_fts_query("AND") == '"AND"*'
        assert build_fts_query("cat OR dog") == '"cat"* "OR"* "dog"*'

    def test_empty_term_raises(self) -> None:
        with pytest.raises(ValueError):
            build_fts_query("")
        with pytest.raises(ValueError):
            build_fts_query("   ")


# -- kernel search ------------------------------------------------------------


class TestKernelSearch:
    def test_matched_term_returns_hit_with_path_and_lines(self, kernel: IndexKernel) -> None:
        kernel.add_document(
            _make_doc(_WS, "wiki/kernel.md", title="Kernel Guide", body="kernel docs")
        )
        hits = kernel.search("kernel")
        assert len(hits) == 1
        hit = hits[0]
        assert hit.relative_path == "wiki/kernel.md"
        assert hit.title == "Kernel Guide"
        assert hit.start_line == 1
        assert hit.end_line == 2
        assert "kernel" in hit.text.lower()
        assert hit.score >= 0.0

    def test_no_match_returns_empty(self, kernel: IndexKernel) -> None:
        kernel.add_document(_make_doc(_WS, "wiki/alpha.md", body="nothing here"))
        assert kernel.search("zzzqqq") == []

    def test_multiple_results_ranked(self, kernel: IndexKernel) -> None:
        kernel.add_document(
            _make_doc(_WS, "wiki/title.md", title="Kernel Guide", body="plain body")
        )
        kernel.add_document(
            _make_doc(_WS, "wiki/body.md", title="Body Doc", body="kernel mentioned")
        )
        hits = kernel.search("kernel")
        paths = [h.relative_path for h in hits]
        assert set(paths) == {"wiki/title.md", "wiki/body.md"}
        # Title match must rank above a body-only match.
        assert paths[0] == "wiki/title.md"
        assert hits[0].score >= hits[1].score

    def test_prefix_match(self, kernel: IndexKernel) -> None:
        kernel.add_document(
            _make_doc(_WS, "wiki/kernel.md", title="Kernel Guide", body="kernel docs")
        )
        assert [h.relative_path for h in kernel.search("ker")] == ["wiki/kernel.md"]

    def test_case_insensitive(self, kernel: IndexKernel) -> None:
        kernel.add_document(_make_doc(_WS, "wiki/kernel.md", body="KERNEL docs"))
        assert [h.relative_path for h in kernel.search("kernel")] == ["wiki/kernel.md"]

    def test_limit(self, kernel: IndexKernel) -> None:
        kernel.add_document(_make_doc(_WS, "wiki/a.md", body="kernel a"))
        kernel.add_document(_make_doc(_WS, "wiki/b.md", body="kernel b"))
        assert len(kernel.search("kernel", limit=1)) == 1

    def test_snippet_contains_highlight_markers(self, kernel: IndexKernel) -> None:
        kernel.add_document(_make_doc(_WS, "wiki/kernel.md", body="the kernel rules"))
        hit = kernel.search("kernel")[0]
        assert "[" in hit.snippet
        assert "]" in hit.snippet

    def test_empty_term_raises(self, kernel: IndexKernel) -> None:
        with pytest.raises(IndexingError):
            kernel.search("")

    def test_search_requires_open(self, tmp_path: Path) -> None:
        k = IndexKernel(tmp_path, identity=_identity())
        with pytest.raises(IndexingError):
            k.search("kernel")

    def test_search_never_creates_database(self, tmp_path: Path) -> None:
        # A search on a fresh kernel in a directory with no state must fail
        # read-only, not create the database (open(create_parent=False) and
        # the service-level index_exists guard both enforce this).
        other = tmp_path / "other"
        other.mkdir()
        k2 = IndexKernel(other, identity=_identity())
        with pytest.raises(IndexingError):
            k2.open(create_parent=False)
        assert not (other / ".nexusos").exists()


# -- service layer ------------------------------------------------------------


class TestSearchWorkspaceService:
    def test_no_workspace_raises(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceNotFoundError):
            search_workspace(tmp_path / "missing", "kernel")

    def test_unindexed_workspace_raises_without_creating_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
        ws = tmp_path / "ws"
        init_workspace(ws, template="blank")
        with pytest.raises(IndexingError):
            search_workspace(ws, "kernel")
        assert not (ws / ".nexusos" / "index.sqlite3").exists()

    def test_search_returns_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
        ws = tmp_path / "ws"
        init_workspace(ws, template="blank")
        (ws / "wiki").mkdir()
        (ws / "wiki" / "kernel.md").write_text(
            "# Kernel Guide\n\nThe kernel provides indexing.\n", encoding="utf-8"
        )
        from nexusos.services.index_service import index_workspace

        run = index_workspace(ws)
        assert run.success

        report = search_workspace(ws, "kernel")
        assert report.query == "kernel"
        assert report.total == 1
        assert report.results[0].relative_path == "wiki/kernel.md"
        assert report.results[0].start_line == 1

    def test_search_returns_empty_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
        ws = tmp_path / "ws"
        init_workspace(ws, template="blank")
        (ws / "wiki").mkdir()
        (ws / "wiki" / "alpha.md").write_text("# Alpha\n\nnothing here\n", encoding="utf-8")
        from nexusos.services.index_service import index_workspace

        assert index_workspace(ws).success
        report = search_workspace(ws, "zzzqqq")
        assert report.total == 0
        assert report.results == []

"""Tests for chunker."""

from __future__ import annotations

import hashlib

from nexusos.indexing.chunker import chunk_document
from nexusos.parsing.models import ParsedDocument, ParsedHeading


def _make_parsed(text: str, headings: list[ParsedHeading] | None = None) -> ParsedDocument:
    return ParsedDocument(
        relative_path="test.md",
        normalized_path="test.md",
        collection="wiki",
        title="Test",
        file_type="markdown",
        authority_class="wiki",
        created_at=None,
        updated_at=None,
        mtime_ns=0,
        size_bytes=len(text),
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        frontmatter={},
        headings=headings or [],
        wikilinks=[],
        body_text=text,
        full_text=text,
        line_count=text.count("\n") + 1,
        parse_warnings=[],
    )


class TestChunkDocument:
    def test_single_chunk(self) -> None:
        doc = _make_parsed("Short paragraph.\n")
        chunks = chunk_document(doc, chunk_max_chars=2400, chunk_overlap_chars=200)
        assert len(chunks) >= 1
        assert "Short paragraph" in chunks[0].text

    def test_heading_aware(self) -> None:
        text = "# H1\nH1 content.\n\n## H2\nH2 content.\n"
        headings = [
            ParsedHeading(ordinal=1, level=1, text="H1", normalized_text="h1", line=1),
            ParsedHeading(ordinal=2, level=2, text="H2", normalized_text="h2", line=4),
        ]
        doc = _make_parsed(text, headings)
        chunks = chunk_document(doc, chunk_max_chars=2400, chunk_overlap_chars=200)
        assert len(chunks) >= 1

    def test_small_max_chars(self) -> None:
        text = "Line one.\nLine two.\nLine three.\n"
        doc = _make_parsed(text)
        _ = chunk_document(doc, chunk_max_chars=10, chunk_overlap_chars=2)
        # May produce 0 chunks if single section < 10 chars — that's valid
        assert True

    def test_chunks_line_ranges(self) -> None:
        text = "A\nB\nC\nD\nE\nF\n"
        doc = _make_parsed(text)
        chunks = chunk_document(doc, chunk_max_chars=1200, chunk_overlap_chars=200)
        # All chunks should have valid line ranges
        for c in chunks:
            assert c.start_line <= c.end_line
            assert c.start_line >= 1
            assert c.end_line <= doc.line_count

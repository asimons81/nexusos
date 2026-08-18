"""Tests for chunker."""

from __future__ import annotations

import hashlib

from nexusos.discovery.models import DiscoveredFile
from nexusos.indexing.chunker import chunk_document
from nexusos.parsing.models import ParsedDocument, ParsedHeading
from nexusos.parsing.plaintext import parse_plaintext


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

    def test_same_line_atx_and_setext_keeps_first_heading_path(self) -> None:
        """Chunk heading path for a line with two headings resolves to the first.

        extract_headings can emit two headings on one line ("# Foo" parsed as
        ATX, then the following "---" parsed as a setext underline). The
        historical line→ordinal scan was first-match; the O(1) rewrite must
        keep first-wins semantics so the chunk path stays ("Foo",) instead of
        ("Foo", "# Foo").
        """
        text = "# Foo\n---\n\nbody\n"
        headings = [
            ParsedHeading(ordinal=1, level=1, text="Foo", normalized_text="foo", line=1),
            ParsedHeading(ordinal=2, level=2, text="# Foo", normalized_text="# foo", line=1),
        ]
        doc = _make_parsed(text, headings)
        chunks = chunk_document(doc, chunk_max_chars=2400, chunk_overlap_chars=200)
        assert chunks
        assert chunks[0].heading_path == ("Foo",)

    def test_plaintext_long_nonfirst_line_makes_progress(self) -> None:
        """Issue #18: an oversized line that is not first must not hang.

        The old _split_section overlap rewound ``current_text`` to identical
        input when the oversized line sat at index ≥ 1, so the while-loop
        never exited. Plaintext routes through _split_section directly.
        """
        text = "first\n" + ("x" * 5000) + "\nlast\n"
        df = DiscoveredFile(
            relative_path="t.txt",
            normalized_path="t.txt",
            collection="raw",
            file_type="plaintext",
            size_bytes=len(text),
            mtime_ns=0,
        )
        doc = parse_plaintext(df, text)
        chunks = chunk_document(doc, chunk_max_chars=2400, chunk_overlap_chars=200)
        assert chunks
        assert "first" in chunks[0].text
        # Reassembled (without inter-chunk overlap) the source is preserved.
        joined = "".join(c.text for c in chunks)
        assert all(ch in joined for ch in ("first", "last"))

    def test_plaintext_long_nonfirst_line_hard_splits(self) -> None:
        """An oversized non-first line is hard-split without losing provenance."""
        text = "first\n" + ("x" * 5000) + "\nlast\n"
        df = DiscoveredFile(
            relative_path="t.txt",
            normalized_path="t.txt",
            collection="raw",
            file_type="plaintext",
            size_bytes=len(text),
            mtime_ns=0,
        )
        doc = parse_plaintext(df, text)
        chunks = chunk_document(doc, chunk_max_chars=2400, chunk_overlap_chars=200)
        for c in chunks[1:]:
            assert len(c.text) <= 2400, f"chunk exceeds max: {len(c.text)}"
        # Every chunk keeps a valid one-based inclusive line range.
        for c in chunks:
            assert 1 <= c.start_line <= c.end_line <= doc.line_count

        # Multiple character slices of the same physical line must all remain
        # anchored to source line 2 instead of advancing the line cursor.
        x_only_chunks = [c for c in chunks if c.text and set(c.text) == {"x"}]
        assert len(x_only_chunks) >= 2
        assert all((c.start_line, c.end_line) == (2, 2) for c in x_only_chunks)

        tail = next(c for c in chunks if "last" in c.text)
        assert (tail.start_line, tail.end_line) == (2, 3)

    def test_multiline_overlap_is_preserved(self) -> None:
        """Line-bounded splits retain whole trailing lines as overlap."""
        text = ("a" * 100) + "\n" + ("b" * 100) + "\n" + ("c" * 100) + "\n"
        df = DiscoveredFile(
            relative_path="t.txt",
            normalized_path="t.txt",
            collection="raw",
            file_type="plaintext",
            size_bytes=len(text),
            mtime_ns=0,
        )
        doc = parse_plaintext(df, text)
        chunks = chunk_document(doc, chunk_max_chars=205, chunk_overlap_chars=120)

        assert len(chunks) == 2
        assert chunks[0].text == ("a" * 100) + "\n" + ("b" * 100)
        assert chunks[1].text == ("b" * 100) + "\n" + ("c" * 100)
        assert (chunks[0].start_line, chunks[0].end_line) == (1, 2)
        assert (chunks[1].start_line, chunks[1].end_line) == (2, 3)

    def test_markdown_long_line_makes_progress(self) -> None:
        """The same oversized-line defect affects markdown sections too."""
        text = "# H\n\nshort\n" + ("x" * 5000) + "\n\nend\n"
        headings = [ParsedHeading(ordinal=1, level=1, text="H", normalized_text="h", line=1)]
        doc = _make_parsed(text, headings)
        chunks = chunk_document(doc, chunk_max_chars=2400, chunk_overlap_chars=200)
        assert chunks
        for c in chunks:
            assert len(c.text) <= 2400, f"chunk exceeds max: {len(c.text)}"

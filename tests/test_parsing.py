"""Tests for Markdown + plaintext parsing."""

from __future__ import annotations

from nexusos.discovery.models import DiscoveredFile
from nexusos.parsing.frontmatter import extract_frontmatter
from nexusos.parsing.headings import extract_headings
from nexusos.parsing.markdown import parse_markdown
from nexusos.parsing.plaintext import parse_plaintext
from nexusos.parsing.wikilinks import extract_wikilinks


def _discovered(rel: str, file_type: str = "markdown") -> DiscoveredFile:
    return DiscoveredFile(
        relative_path=rel,
        normalized_path=rel,
        collection="wiki",
        size_bytes=100,
        mtime_ns=0,
        file_type=file_type,
    )


class TestFrontmatter:
    def test_valid_yaml(self) -> None:
        lines = ["---", "title: Hello", "tags: [a, b]", "---", "", "# Body"]
        text = "\n".join(lines)
        fm, body, line, _warnings = extract_frontmatter(text)
        assert fm == {"title": "Hello", "tags": ["a", "b"]}
        assert "# Body" in body
        assert line == 5

    def test_no_frontmatter(self) -> None:
        text = "# Just a heading\n\nContent."
        fm, _body, _line, _warnings = extract_frontmatter(text)
        assert fm == {}

    def test_empty_frontmatter(self) -> None:
        text = "---\n---\n\nBody"
        fm, body, _line, _warnings = extract_frontmatter(text)
        assert fm == {}
        assert "Body" in body


class TestHeadings:
    def test_atx_headings(self) -> None:
        lines = ["# H1", "## H2", "### H3"]
        headings = extract_headings(lines)
        assert len(headings) == 3
        assert headings[0].level == 1
        assert headings[0].text == "H1"
        assert headings[1].level == 2
        assert headings[2].level == 3

    def test_setext(self) -> None:
        lines = ["H1", "===", "", "H2", "---"]
        headings = extract_headings(lines)
        assert len(headings) == 2
        assert headings[0].text == "H1"
        assert headings[1].text == "H2"

    def test_in_code_fence(self) -> None:
        lines = ["```", "# not a heading", "```", "# real heading"]
        headings = extract_headings(lines)
        assert len(headings) == 1
        assert headings[0].text == "real heading"

    def test_heading_with_leading_whitespace(self) -> None:
        lines = ["   ## Indented H2"]
        headings = extract_headings(lines)
        assert len(headings) == 1
        assert headings[0].level == 2


class TestWikilinks:
    def test_simple_wikilink(self) -> None:
        lines = ["[[simple]]"]
        links = extract_wikilinks(lines)
        assert len(links) == 1
        assert links[0].target_slug == "simple"
        assert links[0].raw_target == "[[simple]]"
        assert links[0].label is None
        assert links[0].target_heading is None

    def test_with_label(self) -> None:
        lines = ["[[target|Display Name]]"]
        links = extract_wikilinks(lines)
        assert len(links) == 1
        assert links[0].target_slug == "target"
        assert links[0].label == "Display Name"

    def test_with_heading(self) -> None:
        lines = ["[[target#section]]"]
        links = extract_wikilinks(lines)
        assert links[0].target_heading == "section"

    def test_with_path(self) -> None:
        lines = ["[[folder/target]]"]
        links = extract_wikilinks(lines)
        assert links[0].target_slug == "folder/target"

    def test_with_label_and_heading(self) -> None:
        lines = ["[[target#section|Custom]]"]
        links = extract_wikilinks(lines)
        assert links[0].target_slug == "target"
        assert links[0].target_heading == "section"
        assert links[0].label == "Custom"

    def test_in_code_fence(self) -> None:
        lines = ["```", "[[not a link]]", "```", "[[real link]]"]
        links = extract_wikilinks(lines)
        assert len(links) == 1
        assert links[0].target_slug == "real link"

    def test_multiple_wikilinks(self) -> None:
        lines = ["[[a]] and [[b]] and [[c]]"]
        links = extract_wikilinks(lines)
        assert len(links) == 3


class TestParseMarkdown:
    def test_full_parse(self) -> None:
        text = "---\ntitle: Test\n---\n\n# Main\n\n[[target]]\n\nContent."
        df = _discovered("test.md")
        doc = parse_markdown(df, text)
        assert doc.title == "Test"
        assert doc.frontmatter == {"title": "Test"}
        assert len(doc.headings) == 1
        assert doc.headings[0].text == "Main"
        assert len(doc.wikilinks) == 1
        assert doc.file_type == "markdown"

    def test_title_from_h1(self) -> None:
        text = "# Main Title\n\nContent."
        df = _discovered("test.md")
        doc = parse_markdown(df, text)
        assert doc.title == "Main Title"

    def test_title_from_filename(self) -> None:
        text = "Content without headings."
        df = _discovered("My-Page.md")
        doc = parse_markdown(df, text)
        assert doc.title == "My-Page"

    def test_frontmatter_title_wins(self) -> None:
        text = "---\ntitle: FM Title\n---\n\n# H1 Title"
        df = _discovered("test.md")
        doc = parse_markdown(df, text)
        assert doc.title == "FM Title"

    def test_wikilinks_in_code_fence_ignored(self) -> None:
        text = "```\n[[ignored]]\n```\n[[real]]"
        df = _discovered("test.md")
        doc = parse_markdown(df, text)
        links = [w for w in doc.wikilinks if w.target_slug == "ignored"]
        assert len(links) == 0


class TestParsePlaintext:
    def test_basic(self) -> None:
        df = _discovered("notes.txt", file_type="plaintext")
        doc = parse_plaintext(df, "Line 1\nLine 2")
        assert doc.title == "notes"
        assert doc.file_type == "plaintext"
        assert doc.frontmatter == {}
        assert doc.headings == []
        assert doc.wikilinks == []
        assert doc.line_count == 2

    def test_title_from_filename(self) -> None:
        df = _discovered("My-Notes.txt", file_type="plaintext")
        doc = parse_plaintext(df, "content")
        assert doc.title == "My-Notes"

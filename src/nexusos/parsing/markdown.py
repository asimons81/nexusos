"""Markdown document parser.

Extracts frontmatter, headings, wiki-links, and body text.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence  # noqa: TC003

from nexusos.core.link_suffixes import LINK_SUFFIXES
from nexusos.discovery.models import DiscoveredFile
from nexusos.parsing.frontmatter import extract_frontmatter
from nexusos.parsing.headings import extract_headings
from nexusos.parsing.models import ParsedDocument
from nexusos.parsing.wikilinks import extract_wikilinks


def parse_markdown(
    discovered: DiscoveredFile,
    source_text: str,
) -> ParsedDocument:
    """Parse a Markdown document from its full source text.

    Extracts frontmatter, headings, wiki-links, and computes derived metadata.
    Content is treated as untrusted data.
    """
    lines = source_text.split("\n")
    content_sha256 = hashlib.sha256(source_text.encode()).hexdigest()
    parse_warnings: list[str] = []

    # Frontmatter
    frontmatter, body_text, body_start_line, fm_warnings = extract_frontmatter(source_text)
    parse_warnings.extend(fm_warnings)

    # Headings (only from body, not frontmatter)
    all_headings = extract_headings(lines, body_start_line=body_start_line)

    # Wiki-links from body only (so they don't match inside frontmatter)
    body_lines = source_text.split("\n")
    body_wikilinks = extract_wikilinks(body_lines)

    # Title resolution
    title = _resolve_title(frontmatter, all_headings, discovered.normalized_path)

    # Tags from frontmatter
    tags: list[str] = []
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, list):
        tags = [str(t) for t in fm_tags]

    # Authority class from frontmatter
    authority_class = str(frontmatter.get("authority_class", "unknown"))

    # Created/updated from frontmatter
    created_at = _as_optional_iso(frontmatter.get("created"))
    updated_at = _as_optional_iso(frontmatter.get("updated"))

    # Determine body text: everything after frontmatter
    full_text = source_text

    return ParsedDocument(
        relative_path=discovered.relative_path,
        normalized_path=discovered.normalized_path,
        collection=discovered.collection,
        file_type="markdown",
        title=title,
        frontmatter=frontmatter,
        body_text=body_text,
        full_text=full_text,
        created_at=created_at,
        updated_at=updated_at,
        authority_class=authority_class,
        tags=tags,
        headings=all_headings,
        wikilinks=body_wikilinks,
        line_count=len(lines),
        size_bytes=discovered.size_bytes,
        mtime_ns=discovered.mtime_ns,
        content_sha256=content_sha256,
        parse_warnings=parse_warnings,
    )


def _resolve_title(
    frontmatter: dict[str, object],
    headings: Sequence[object],
    normalized_path: str,
) -> str:
    """Resolve document title: frontmatter 'title' > first H1 > filename stem."""
    fm_title = frontmatter.get("title")
    if fm_title is not None and str(fm_title).strip():
        return str(fm_title).strip()

    for h in headings:
        if getattr(h, "level", 0) == 1:
            return str(getattr(h, "text", ""))

    # Filename stem
    name = normalized_path.rsplit("/", 1)[-1]
    for suffix in LINK_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def _as_optional_iso(value: object) -> str | None:
    """Convert a frontmatter date-like value to an ISO string or None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s

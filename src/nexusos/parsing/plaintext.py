"""Plain-text document parser.

Plain-text files have no frontmatter, no headings, and use the filename stem
as title. They are chunked using paragraph/line boundaries at a higher level.
"""

from __future__ import annotations

import hashlib

from nexusos.core.link_suffixes import LINK_SUFFIXES
from nexusos.discovery.models import DiscoveredFile
from nexusos.parsing.models import ParsedDocument


def parse_plaintext(
    discovered: DiscoveredFile,
    source_text: str,
) -> ParsedDocument:
    """Parse a plain-text document.

    Returns a parsed document with no frontmatter, no headings, and
    the filename stem as title.
    """
    lines = source_text.split("\n")
    content_sha256 = hashlib.sha256(source_text.encode()).hexdigest()

    title = _filename_stem(discovered.normalized_path)

    return ParsedDocument(
        relative_path=discovered.relative_path,
        normalized_path=discovered.normalized_path,
        collection=discovered.collection,
        file_type="plaintext",
        title=title,
        frontmatter={},
        body_text=source_text,
        full_text=source_text,
        created_at=None,
        updated_at=None,
        authority_class="unknown",
        tags=[],
        headings=[],
        wikilinks=[],
        line_count=len(lines),
        size_bytes=discovered.size_bytes,
        mtime_ns=discovered.mtime_ns,
        content_sha256=content_sha256,
        parse_warnings=[],
    )


def _filename_stem(normalized_path: str) -> str:
    name = normalized_path.rsplit("/", 1)[-1]
    for suffix in LINK_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name

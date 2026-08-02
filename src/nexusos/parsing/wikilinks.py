"""Wiki-link extraction from Markdown source.

Supports:
    [[target]]
    [[target|Display Label]]
    [[folder/target]]
    [[target#Heading]]
    [[target#Heading|Display Label]]
"""

from __future__ import annotations

import re

from nexusos.parsing.models import ParsedWikiLink

# Match [[target]] or [[target|label]] (does not cross fences)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#([^\]|]+?))?(?:\|([^\]]+?))?\]\]")


def extract_wikilinks(lines: list[str], *, start_line: int = 1) -> list[ParsedWikiLink]:
    """Extract wiki-links from source lines.

    Fenced code blocks are ignored. Returns links with source line numbers
    (1-based, relative to ``start_line``).
    """
    links: list[ParsedWikiLink] = []
    in_fence = False

    for idx, raw_line in enumerate(lines):
        stripped = raw_line.rstrip()

        # Track code fences
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue

        if in_fence:
            continue

        line_num = start_line + idx
        for m in _WIKILINK_RE.finditer(raw_line):
            target = m.group(1).strip()
            heading = m.group(2).strip() if m.group(2) else None
            label = m.group(3).strip() if m.group(3) else None

            slug = _normalize_slug(target)

            links.append(
                ParsedWikiLink(
                    source_line=line_num,
                    raw_target=m.group(0),
                    target_slug=slug,
                    target_heading=heading or None,
                    label=label,
                )
            )

    return links


def _normalize_slug(target: str) -> str:
    """Normalize a wiki-link target into a forward-slash relative slug."""
    slug = target.replace("\\", "/").strip()
    while slug.startswith("./"):
        slug = slug[2:]
    # Strip .md/.markdown/.txt suffix for slug (document resolution strips those)
    for suffix in (".markdown", ".md", ".txt"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
            break
    return slug

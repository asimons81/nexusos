"""Heading extraction from Markdown source.

Supports ATX headings (#, ##, …) and Setext headings (===, ---).
Headings inside fenced code blocks are ignored.
"""

from __future__ import annotations

from nexusos.parsing.models import ParsedHeading


def extract_headings(lines: list[str], *, body_start_line: int = 1) -> list[ParsedHeading]:
    """Extract all headings from Markdown source lines.

    Returns headings with their ordinal (1-based), level, text,
    normalized text, and line number (1-based). Headings inside
    fenced code blocks and lines before body_start_line are ignored.
    """
    headings: list[ParsedHeading] = []
    in_fence = False

    for idx, line in enumerate(lines):
        line_num = idx + 1
        if line_num < body_start_line:
            continue
        stripped = line.rstrip()

        # Track code fences
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue

        if in_fence:
            continue

        heading = _try_atx(stripped)
        if heading is not None:
            level, text = heading
            ordinal = len(headings) + 1
            normalized = " ".join(text.lower().split())
            headings.append(
                ParsedHeading(
                    level=level,
                    text=text.strip(),
                    normalized_text=normalized,
                    line=line_num,
                    ordinal=ordinal,
                )
            )

        # Setext: next line must be all === or --- (at least 3 chars)
        # Skip Setext if current line is before body start
        if line_num < body_start_line:
            continue
        heading = _try_setext(lines, idx)
        if heading is not None:
            level, text = heading
            ordinal = len(headings) + 1
            normalized = " ".join(text.lower().split())
            headings.append(
                ParsedHeading(
                    level=level,
                    text=text.strip(),
                    normalized_text=normalized,
                    line=idx + 1,
                    ordinal=ordinal,
                )
            )

    return headings


def _try_atx(line: str) -> tuple[int, str] | None:
    """Try to parse an ATX heading. Returns (level, text) or None."""
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    # Count leading #s
    level = 0
    for ch in stripped:
        if ch == "#":
            level += 1
        else:
            break
    if level < 1 or level > 6:
        return None
    # Require space after #s (or end of string for closing #s)
    if level < len(stripped) and stripped[level] != " ":
        return None
    text = stripped[level:].strip()
    # Strip trailing #s
    while text.endswith("#"):
        text = text[:-1].rstrip()
    return level, text


def _try_setext(lines: list[str], idx: int) -> tuple[int, str] | None:
    """Try to parse a Setext heading. The heading text is on line idx,
    the underline (=== or ---) must be on the next line."""
    if idx + 1 >= len(lines):
        return None
    text = lines[idx].strip()
    if not text:
        return None
    underline = lines[idx + 1].strip()
    if not underline:
        return None
    if all(ch == "=" for ch in underline) and len(underline) >= 3:
        return 1, text
    if all(ch == "-" for ch in underline) and len(underline) >= 3:
        return 2, text
    return None


def build_heading_hierarchy(headings: list[ParsedHeading]) -> dict[int, tuple[str, ...]]:
    """Build the ancestor heading-path hierarchy in a single O(n) pass.

    Returns a mapping from heading ordinal to its full ancestor chain as a
    tuple of heading texts, e.g. ``{1: ("Intro",), 2: ("Intro", "Details")}``.
    Uses an explicit (level, text) stack so each heading is pushed and popped
    at most once — no rescans, no quadratic blowup.
    """
    hierarchy: dict[int, tuple[str, ...]] = {}
    stack: list[tuple[int, str]] = []  # (level, text)

    for h in headings:
        while stack and stack[-1][0] >= h.level:
            stack.pop()
        stack.append((h.level, h.text))
        hierarchy[h.ordinal] = tuple(item[1] for item in stack)

    return hierarchy


def build_heading_path(headings: list[ParsedHeading], up_to_ordinal: int) -> list[str]:
    """Build the heading path (hierarchy) for a given heading ordinal.

    Returns the full ancestor chain as a list of heading texts, e.g.
    ["Introduction", "Background", "Details"]. For an ordinal between two
    headings (or past the end), returns the chain as of the last heading
    with ``ordinal <= up_to_ordinal``; empty if none.
    """
    best: tuple[str, ...] = ()
    for ordinal, path in build_heading_hierarchy(headings).items():
        if ordinal <= up_to_ordinal:
            best = path
        else:
            break
    return list(best)

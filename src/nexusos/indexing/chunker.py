"""Deterministic heading-aware document chunker.

Produces source-preserving chunks from parsed documents. Every chunk preserves
exact source text and one-based inclusive line ranges.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from nexusos.parsing.models import ParsedDocument, ParsedHeading


class ChunkCandidate(BaseModel):
    """A chunk produced by the chunker, before identifier assignment."""

    model_config = ConfigDict(frozen=True)

    ordinal: int = Field(ge=1)
    heading_path: tuple[str, ...] = Field(default_factory=tuple)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    text: str
    content_sha256: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _build_heading_hierarchy(
    headings: list[ParsedHeading],
) -> dict[int, tuple[str, ...]]:
    """Build a map from heading ordinal → heading path (ancestor chain)."""
    hierarchy: dict[int, tuple[str, ...]] = {}
    stack: list[tuple[int, str]] = []  # (level, text)

    for h in headings:
        while stack and stack[-1][0] >= h.level:
            stack.pop()
        stack.append((h.level, h.text))
        hierarchy[h.ordinal] = tuple(item[1] for item in stack)

    return hierarchy


def chunk_document(
    doc: ParsedDocument,
    chunk_max_chars: int = 2400,
    chunk_overlap_chars: int = 200,
) -> list[ChunkCandidate]:
    """Chunk a parsed document into heading-aware sections.

    Returns a deterministic, ordered list of chunk candidates.
    """
    if doc.file_type == "plaintext":
        return _chunk_plaintext(doc, chunk_max_chars, chunk_overlap_chars)
    return _chunk_markdown(doc, chunk_max_chars, chunk_overlap_chars)


def _chunk_markdown(
    doc: ParsedDocument,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
) -> list[ChunkCandidate]:
    """Chunk a markdown document heading-by-heading."""
    lines = doc.full_text.split("\n")
    headings = doc.headings
    hierarchy = _build_heading_hierarchy(headings)

    # Find body start (after frontmatter)
    body_start = 1
    fm = doc.frontmatter
    if fm:
        # Find the closing --- line
        for i, line in enumerate(lines):
            if i == 0 and line.strip() == "---":
                continue
            if line.strip() == "---":
                body_start = i + 2  # 1-based, after the closing ---
                break

    if body_start > len(lines):
        # Empty body — no chunks
        return []

    # Identify heading sections: each section starts at a heading line
    # and runs until the next heading at the same or higher level.
    heading_lines: set[int] = {h.line for h in headings}
    section_start = body_start
    current_heading_ordinal: int | None = None

    sections: list[tuple[int, int, tuple[str, ...]]] = []  # (start, end, heading_path)

    for line_num in range(body_start, len(lines) + 1):
        if line_num in heading_lines:
            if section_start < line_num:
                # End previous section
                path = hierarchy.get(current_heading_ordinal, ()) if current_heading_ordinal else ()
                sections.append((section_start, line_num - 1, path))
            section_start = line_num
            # Find the heading ordinal for this line
            for h in headings:
                if h.line == line_num:
                    current_heading_ordinal = h.ordinal
                    break

    # Final section
    if section_start <= len(lines):
        path = hierarchy.get(current_heading_ordinal, ()) if current_heading_ordinal else ()
        sections.append((section_start, len(lines), path))

    # Now chunk each section
    chunks: list[ChunkCandidate] = []

    for section_start_line, section_end_line, heading_path in sections:
        if section_start_line > section_end_line:
            continue

        section_text = "\n".join(lines[section_start_line - 1 : section_end_line])
        section_len = len(section_text)

        if section_len <= chunk_max_chars:
            text = section_text.strip()
            if text:
                chunks.append(
                    ChunkCandidate(
                        ordinal=len(chunks) + 1,
                        heading_path=heading_path,
                        start_line=section_start_line,
                        end_line=section_end_line,
                        text=text,
                        content_sha256=_sha256(text),
                    )
                )
        else:
            # Split oversized section at paragraph boundaries
            subs = _split_section(
                lines,
                section_start_line,
                section_end_line,
                chunk_max_chars,
                chunk_overlap_chars,
                heading_path,
            )
            chunks.extend(subs)

    # Renumber ordinals
    for i, chunk in enumerate(chunks):
        chunks[i] = chunk.model_copy(update={"ordinal": i + 1})

    return chunks


def _split_section(
    lines: list[str],
    start_line: int,
    end_line: int,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
    heading_path: tuple[str, ...],
) -> list[ChunkCandidate]:
    """Split an oversized section at paragraph boundaries."""
    candidates: list[ChunkCandidate] = []

    # Identify paragraph boundaries (blank lines)
    paragraphs: list[tuple[int, int]] = []
    para_start = start_line
    for i in range(start_line, end_line + 1):
        if i > end_line:
            break
        if lines[i - 1].strip() == "":
            if para_start < i:
                paragraphs.append((para_start, i - 1))
            para_start = i + 1

    if para_start <= end_line:
        paragraphs.append((para_start, end_line))

    # Now split paragraphs into chunks
    current_text = ""
    current_start = 0

    for p_start, p_end in paragraphs:
        para_text = "\n".join(lines[p_start - 1 : p_end])
        if not para_text.strip():
            continue

        if not current_text:
            current_text = para_text
            current_start = p_start
        else:
            combined = current_text + "\n\n" + para_text
            if len(combined) <= chunk_max_chars:
                current_text = combined
            else:
                # Flush current chunk
                candidates.append(
                    ChunkCandidate(
                        ordinal=len(candidates) + 1,
                        heading_path=heading_path,
                        start_line=current_start,
                        end_line=p_start - 1,
                        text=current_text.strip(),
                        content_sha256=_sha256(current_text.strip()),
                    )
                )
                # Start new chunk with overlap
                current_text = para_text
                current_start = p_start

        # If current paragraph is still too big, split at line boundaries
        while len(current_text) > chunk_max_chars and current_text != current_text.split("\n")[0]:
            para_lines = current_text.split("\n")
            # Find split point
            split_at = 0
            acc = 0
            for j, pline in enumerate(para_lines):
                if acc + len(pline) > chunk_max_chars and j > 0:
                    split_at = j
                    break
                acc += len(pline) + 1  # +1 for newline

            if split_at == 0:
                split_at = len(para_lines)

            chunk_lines = para_lines[:split_at]
            chunk_text = "\n".join(chunk_lines).strip()
            chunk_end_line = current_start + len(chunk_lines) - 1

            candidates.append(
                ChunkCandidate(
                    ordinal=len(candidates) + 1,
                    heading_path=heading_path,
                    start_line=current_start,
                    end_line=chunk_end_line,
                    text=chunk_text,
                    content_sha256=_sha256(chunk_text),
                )
            )

            # Overlap: keep the last few lines as context for next chunk
            if split_at < len(para_lines):
                overlap_start = max(0, split_at - _overlap_lines(chunk_lines, chunk_overlap_chars))
                remaining = para_lines[overlap_start:]
                current_text = "\n".join(remaining)
                current_start = current_start + overlap_start
            else:
                current_text = ""
                current_start = 0

    # Flush final chunk
    if current_text.strip():
        # Find end line
        last_line = current_start + len(current_text.split("\n")) - 1
        candidates.append(
            ChunkCandidate(
                ordinal=len(candidates) + 1,
                heading_path=heading_path,
                start_line=current_start,
                end_line=min(last_line, end_line),
                text=current_text.strip(),
                content_sha256=_sha256(current_text.strip()),
            )
        )

    return candidates


def _overlap_lines(lines: list[str], max_chars: int) -> int:
    """Return how many lines from the end to keep for overlap."""
    total = 0
    count = 0
    for line in reversed(lines):
        if total + len(line) > max_chars:
            break
        total += len(line) + 1
        count += 1
    return count


def _chunk_plaintext(
    doc: ParsedDocument,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
) -> list[ChunkCandidate]:
    """Chunk a plain-text document using paragraph and line boundaries."""
    lines = doc.full_text.split("\n")

    # Use the same section-based approach, treating the whole document as one section
    return _split_section(lines, 1, len(lines), chunk_max_chars, chunk_overlap_chars, ())

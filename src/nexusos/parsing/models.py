"""Typed models for parsed document content."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParsedHeading(BaseModel):
    """A heading extracted from a source document."""

    model_config = ConfigDict(frozen=True)

    level: int = Field(ge=1, le=6)
    text: str
    normalized_text: str
    line: int = Field(ge=1)
    ordinal: int = Field(ge=1)


class ParsedWikiLink(BaseModel):
    """A wiki-link extracted from a source document."""

    model_config = ConfigDict(frozen=True)

    source_line: int = Field(ge=1)
    raw_target: str
    target_slug: str
    target_heading: str | None = None
    label: str | None = None


class ParsedDocument(BaseModel):
    """A fully parsed document ready for chunking and indexing.

    All content is treated as untrusted data. Line numbers are 1-based.
    """

    model_config = ConfigDict(frozen=True)

    relative_path: str
    normalized_path: str
    collection: str
    file_type: str  # "markdown" | "plaintext"

    title: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body_text: str = ""
    full_text: str = ""

    created_at: str | None = None
    updated_at: str | None = None
    authority_class: str = "unknown"
    tags: list[str] = Field(default_factory=list)

    headings: list[ParsedHeading] = Field(default_factory=list)
    wikilinks: list[ParsedWikiLink] = Field(default_factory=list)

    line_count: int = 0
    size_bytes: int = 0
    mtime_ns: int = 0
    content_sha256: str = ""
    parse_warnings: list[str] = Field(default_factory=list)

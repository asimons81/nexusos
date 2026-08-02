"""Internal models for the NexusOS indexing kernel.

These models describe the *persisted* shape of an indexed document and its
derived rows. They are consumed by the kernel API (add/update/remove/lookup)
and are independent of the higher-level discovery/parsing models. Document
content is always treated as untrusted data: every string field is stored
verbatim and never executed or interpreted.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DOCUMENT_ID_RE = re.compile(r"^nxo_doc_[a-z0-9]{32}$")
_CHUNK_ID_RE = re.compile(r"^nxo_chk_[a-z0-9]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_RESOLUTION_STATES = ("resolved", "unresolved", "ambiguous")
_FILE_TYPES = ("markdown", "plaintext")


class IndexedHeading(BaseModel):
    """A heading extracted from a source document, persisted by the kernel."""

    model_config = ConfigDict(frozen=True)

    ordinal: int = Field(ge=1)
    level: int = Field(ge=1, le=6)
    text: str
    normalized_text: str
    line: int = Field(ge=1)
    heading_path: tuple[str, ...] = Field(default_factory=tuple)


class IndexedChunk(BaseModel):
    """A source-preserving document chunk persisted by the kernel."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    ordinal: int = Field(ge=1)
    heading_path: tuple[str, ...] = Field(default_factory=tuple)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    text: str
    content_sha256: str

    @field_validator("chunk_id")
    @classmethod
    def check_chunk_id(cls, v: str) -> str:
        if not _CHUNK_ID_RE.fullmatch(v):
            raise ValueError(f"chunk_id must match {_CHUNK_ID_RE.pattern!r}, got {v!r}")
        return v

    @field_validator("content_sha256")
    @classmethod
    def check_content_sha256(cls, v: str) -> str:
        if not _SHA256_RE.fullmatch(v):
            raise ValueError(f"content_sha256 must be 64 hex chars, got {v!r}")
        return v

    @model_validator(mode="after")
    def check_line_range(self) -> IndexedChunk:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class IndexedLink(BaseModel):
    """A wiki-link extracted from a source document, persisted by the kernel.

    ``target_document_id`` is populated by graph construction after all current
    documents are known; the kernel persists whatever resolution state the
    caller provides.
    """

    model_config = ConfigDict(frozen=True)

    source_line: int = Field(ge=1)
    raw_target: str
    target_slug: str
    target_heading: str | None = None
    label: str | None = None
    target_document_id: str | None = None
    resolved: bool = False
    resolution_state: str = "unresolved"

    @field_validator("resolution_state")
    @classmethod
    def check_resolution_state(cls, v: str) -> str:
        if v not in _RESOLUTION_STATES:
            raise ValueError(f"resolution_state must be one of {_RESOLUTION_STATES}, got {v!r}")
        return v


class IndexedDocument(BaseModel):
    """A document entry and its derived rows as persisted by the kernel."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    relative_path: str
    normalized_path: str
    collection: str
    title: str
    file_type: str = "markdown"
    authority_class: str = "unknown"
    created_at: str | None = None
    updated_at: str | None = None
    mtime_ns: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    content_sha256: str
    frontmatter_json: str = "{}"
    indexed_at: str
    line_count: int = Field(ge=0)
    parse_warning_count: int = Field(ge=0, default=0)
    headings: list[IndexedHeading] = Field(default_factory=list)
    chunks: list[IndexedChunk] = Field(default_factory=list)
    wikilinks: list[IndexedLink] = Field(default_factory=list)
    #: Tags used only to populate the FTS ``tags`` column (not a persisted column).
    tags: list[str] = Field(default_factory=list)

    @field_validator("document_id")
    @classmethod
    def check_document_id(cls, v: str) -> str:
        if not _DOCUMENT_ID_RE.fullmatch(v):
            raise ValueError(f"document_id must match {_DOCUMENT_ID_RE.pattern!r}, got {v!r}")
        return v

    @field_validator("relative_path", "normalized_path")
    @classmethod
    def check_relative_path(cls, v: str) -> str:
        if not v:
            raise ValueError("path must not be empty")
        if v.startswith("/") or v.startswith("\\"):
            raise ValueError(f"path must be relative, got {v!r}")
        if len(v) >= 2 and v[1] == ":":
            raise ValueError(f"path must be relative, got {v!r}")
        if "\\" in v:
            raise ValueError(f"path must use forward slashes, got {v!r}")
        parts = v.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"path must be normalized, got {v!r}")
        return v

    @field_validator("file_type")
    @classmethod
    def check_file_type(cls, v: str) -> str:
        if v not in _FILE_TYPES:
            raise ValueError(f"file_type must be one of {_FILE_TYPES}, got {v!r}")
        return v

    @field_validator("content_sha256")
    @classmethod
    def check_content_sha256(cls, v: str) -> str:
        if not _SHA256_RE.fullmatch(v):
            raise ValueError(f"content_sha256 must be 64 hex chars, got {v!r}")
        return v

    @model_validator(mode="after")
    def check_chunk_invariants(self) -> IndexedDocument:
        ordinals = [chunk.ordinal for chunk in self.chunks]
        if ordinals != list(range(1, len(self.chunks) + 1)):
            raise ValueError("chunk ordinals must be contiguous starting at 1")
        for chunk in self.chunks:
            if chunk.document_id != self.document_id:
                raise ValueError("chunk document_id must match the owning document")
        return self


class DocumentCandidate(BaseModel):
    """A minimal document row returned by deterministic candidate lookup."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    normalized_path: str
    title: str
    collection: str


class IndexRunRecord(BaseModel):
    """A persisted index-run record used for status reporting."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    started_at: str
    completed_at: str | None = None
    mode: str
    files_seen: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    documents_failed: int = 0
    warning_count: int = 0
    error_count: int = 0
    success: bool = False
    error_summary: str | None = None


class IndexCounts(BaseModel):
    """Row counts for status reporting."""

    model_config = ConfigDict(frozen=True)

    document_count: int
    chunk_count: int
    heading_count: int
    resolved_link_count: int
    unresolved_link_count: int
    ambiguous_link_count: int

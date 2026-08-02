"""Typed models for file discovery results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiscoveredFile(BaseModel):
    """A source file discovered during workspace scanning.

    Contains only what the scanner can determine without reading or parsing
    file content. Document content extraction belongs to ``nexusos.parsing``.
    """

    model_config = ConfigDict(frozen=True)

    relative_path: str
    normalized_path: str
    collection: str
    file_type: str = "markdown"  # "markdown" | "plaintext"
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)


class DiscoveryResult(BaseModel):
    """The result of a workspace discovery scan."""

    model_config = ConfigDict(frozen=True)

    files: list[DiscoveredFile] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)

"""Pydantic models for NexusOS configuration and workspace identity."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceIdentity(BaseModel):
    """Immutable workspace identity stored in .nexusos/workspace.json."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    workspace_id: str
    created_at: str
    nexusos_version: str

    @field_validator("workspace_id")
    @classmethod
    def check_id_prefix(cls, v: str) -> str:
        if not v.startswith("nxo_ws_"):
            raise ValueError(f"workspace_id must start with 'nxo_ws_', got {v!r}")
        if len(v) <= len("nxo_ws_"):
            raise ValueError("workspace_id must have content after 'nxo_ws_' prefix")
        return v


class FileCollectionMapping(BaseModel):
    """Maps a directory pattern to a collection name."""

    model_config = ConfigDict(frozen=True)

    path: str
    collection: str


class NexusOSConfig(BaseModel):
    """Typed configuration model for nexusos.toml and env overrides."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    # Workspace identity
    workspace_name: str = "default"
    root: Path | None = None

    # File patterns
    include_patterns: list[str] = Field(default_factory=lambda: ["**/*.md", "**/*.txt"])
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/.nexusos/**",
            "**/node_modules/**",
            "**/__pycache__/**",
            "**/.git/**",
            "**/.direnv/**",
        ]
    )
    collection_mappings: dict[str, str] = Field(default_factory=dict)

    # Limits
    max_file_size_bytes: int = 10_485_760  # 10 MiB
    symlink_policy: str = "ignore"  # ignore | warn | deny

    # Indexing (future)
    index_path: str = ".nexusos/index.sqlite3"
    chunk_max_chars: int = 2400
    chunk_overlap_chars: int = 200
    default_collection: str = "inbox"

    # Search (future)
    search_max_results: int = 50
    search_snippet_length: int = 200

    # Server (future)
    server_host: str = "127.0.0.1"
    server_port: int = 8765

    # Lint
    lint_max_file_size_bytes: int = 5_242_880  # 5 MiB
    lint_warn_empty_docs: bool = True

    def merge_overrides(self, overrides: dict[str, Any]) -> NexusOSConfig:
        """Return a new config with the given overrides applied."""
        merged = self.model_copy(deep=True)
        for key, value in overrides.items():
            if hasattr(merged, key):
                setattr(merged, key, value)
        return merged

    def to_safe_dict(self) -> dict[str, Any]:
        """Return a dict safe for display (no secrets)."""
        return self.model_dump(mode="json")


DEFAULT_CONFIG = NexusOSConfig()


# Doctor check severity
class CheckStatus:
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class DoctorCheck(BaseModel):
    """A single doctor check result."""

    check: str
    status: str  # pass | warning | fail
    message: str
    detail: str | None = None


class DoctorReport(BaseModel):
    """Structured doctor report."""

    workspace_root: Path | None = None
    checks: list[DoctorCheck] = Field(default_factory=list)
    passed: int = 0
    warnings: int = 0
    failures: int = 0
    healthy: bool = False

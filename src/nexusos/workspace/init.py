"""Workspace initialization with blank and starter templates."""

from __future__ import annotations

import json
import random
import string
from datetime import UTC, datetime
from pathlib import Path

from nexusos import __version__
from nexusos.core.errors import (
    NonEmptyDirectoryError,
    TemplateError,
    WorkspaceAlreadyExistsError,
)
from nexusos.core.models import WorkspaceIdentity
from nexusos.core.path_safety import (
    check_nesting,
    forbid_root_or_home,
    resolve_safe,
)

WSPACE_FILE = ".nexusos/workspace.json"

STARTER_STRUCTURE: dict[str, str] = {
    "nexusos.toml": "config",
    "SCHEMA.md": "file",
    "README.md": "file",
    "inbox/": "dir",
    "raw/": "dir",
    "raw/articles/": "dir",
    "raw/conversations/": "dir",
    "raw/notes/": "dir",
    "raw/transcripts/": "dir",
    "wiki/": "dir",
    "wiki/concepts/": "dir",
    "wiki/entities/": "dir",
    "wiki/projects/": "dir",
    "wiki/queries/": "dir",
    "wiki/_archive/": "dir",
    "ops/": "dir",
    "ops/decisions/": "dir",
    "ops/sops/": "dir",
    "ops/workflows/": "dir",
    "mocs/": "dir",
    "journal/": "dir",
    ".nexusos/": "dir",
}

BLANK_STRUCTURE: dict[str, str] = {
    "nexusos.toml": "config",
    "README.md": "file",
    ".nexusos/": "dir",
}

STARTER_CONFIG = """# NexusOS Workspace Configuration
#
# This is the central configuration for this NexusOS knowledge workspace.
# Environment variables NEXUSOS_* override these values at runtime.
# CLI flags override environment variables.

[workspace]
name = "{workspace_name}"

[files]
include = ["**/*.md", "**/*.txt"]
exclude = [
    "**/.nexusos/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.git/**",
]

[limits]
max_file_size_bytes = 10_485_760
symlink_policy = "ignore"

[collections]
inbox = "inbox"
raw = "raw"
wiki = "wiki"
ops = "ops"
mocs = "mocs"
journal = "journal"

[search]
max_results = 50
snippet_length = 200

[server]
host = "127.0.0.1"
port = 8765

[lint]
max_file_size_bytes = 5_242_880
warn_empty_docs = true
"""

BLANK_CONFIG = """# NexusOS Workspace Configuration

[workspace]
name = "{workspace_name}"

[files]
include = ["**/*.md", "**/*.txt"]
exclude = [
    "**/.nexusos/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.git/**",
]

[limits]
max_file_size_bytes = 10_485_760

[server]
host = "127.0.0.1"
port = 8765
"""

STARTER_README = """# {workspace_name}

Welcome to your NexusOS knowledge workspace.

## Getting Started

1. Add Markdown files to `wiki/`, `raw/`, or `inbox/`
2. Run `nexusos doctor` to verify health
3. Indexing and search will be available in a future release

## Directory Layout

- `inbox/` — Unprocessed items waiting to be classified
- `raw/` — Source documents (articles, conversations, notes, transcripts)
- `wiki/` — Structured knowledge base (concepts, entities, projects, queries)
- `ops/` — Operational documents (decisions, SOPs, workflows)
- `mocs/` — Maps of content (topical indexes)
- `journal/` — Timestamped entries
- `.nexusos/` — Internal state (do not edit)

## Configuration

See `nexusos.toml` for workspace settings. Run `nexusos config show` to review.
"""

BLANK_README = """# {workspace_name}

A NexusOS knowledge workspace. Run `nexusos doctor` to verify health.
"""

STARTER_SCHEMA = """# NexusOS Workspace Schema

This document describes the directory structure and conventions for a NexusOS workspace.

## Directories

| Path | Purpose |
|------|---------|
| `inbox/` | Unprocessed items |
| `raw/articles/` | Imported articles |
| `raw/conversations/` | Chat logs, interviews |
| `raw/notes/` | Quick notes |
| `raw/transcripts/` | Audio/video transcripts |
| `wiki/concepts/` | Topic definitions |
| `wiki/entities/` | People, companies, tools |
| `wiki/projects/` | Active and completed projects |
| `wiki/queries/` | Saved search queries |
| `wiki/_archive/` | Archived wiki pages |
| `ops/decisions/` | Architecture and design decisions |
| `ops/sops/` | Standard operating procedures |
| `ops/workflows/` | Process documentation |
| `mocs/` | Maps of content (topical overviews) |
| `journal/` | Timestamped log entries |

## Conventions

- All documents are Markdown (`.md`)
- YAML frontmatter at the top of wiki pages for metadata
- Wiki links use `[[page-name]]` syntax
"""


def _random_id(prefix: str = "nxo_ws_", length: int = 12) -> str:
    """Generate a cryptographically secure random workspace ID."""
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(random.SystemRandom().choices(alphabet, k=length))
    return f"{prefix}{suffix}"


def _iso_now() -> str:
    """ISO-8601 timestamp in UTC."""
    return datetime.now(UTC).isoformat()


def _atomic_write(path: Path, content: str) -> None:
    """Write a file atomically using a temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _write_if_missing(path: Path, content: str) -> bool:
    """Write content to path only if it doesn't exist. Returns True if written."""
    if path.exists():
        return False
    _atomic_write(path, content)
    return True


def build_workspace_identity() -> WorkspaceIdentity:
    """Build a new workspace identity."""
    return WorkspaceIdentity(
        schema_version=1,
        workspace_id=_random_id(),
        created_at=_iso_now(),
        nexusos_version=__version__,
    )


def _compute_structure(template: str) -> dict[str, str]:
    """Return the directory/file map for a template."""
    if template == "blank":
        return BLANK_STRUCTURE
    if template == "starter":
        return STARTER_STRUCTURE
    raise TemplateError(f"Unknown template: {template}", exit_code=2)


def _compute_plan(
    target: Path,
    template: str,
    *,
    adopt: bool,
    env_deny: str | None,
) -> dict[str, str]:
    """Compute what would be created without writing. Returns path→type map."""
    resolve_safe(target, env_deny=env_deny)
    forbid_root_or_home(target)
    check_nesting(target)

    ws_identity_file = target / WSPACE_FILE
    if ws_identity_file.exists():
        raise WorkspaceAlreadyExistsError(f"Workspace already exists at {target}", exit_code=2)

    # Non-empty check
    if target.exists() and target.is_dir():
        contents = list(target.iterdir())
        if contents and not adopt:
            raise NonEmptyDirectoryError(
                f"Directory {target} is not empty. Use --adopt to adopt it.",
                exit_code=2,
            )

    structure = _compute_structure(template)
    plan: dict[str, str] = {}
    for rel_path, kind in sorted(structure.items()):
        full_path = target / rel_path
        if full_path.exists():
            continue
        plan[rel_path] = kind

    return plan


def init_workspace(
    target: Path,
    *,
    template: str = "starter",
    dry_run: bool = False,
    adopt: bool = False,
    env_deny: str | None = None,
) -> dict[str, str]:
    """Initialize a workspace at target. Returns the plan (what was done)."""
    target = Path(target).expanduser()

    # Safety checks
    resolve_safe(target, env_deny=env_deny)
    forbid_root_or_home(target)
    check_nesting(target)

    # Already exists?
    ws_identity_file = target / WSPACE_FILE
    if ws_identity_file.exists():
        raise WorkspaceAlreadyExistsError(f"Workspace already exists at {target}", exit_code=2)

    # Non-empty check
    if target.exists() and target.is_dir():
        contents = list(target.iterdir())
        if contents and not adopt:
            raise NonEmptyDirectoryError(
                f"Directory {target} is not empty ({len(contents)} items). "
                "Use --adopt to adopt it.",
                exit_code=2,
            )

    plan = _compute_plan(target, template, adopt=adopt, env_deny=env_deny)

    if dry_run:
        return plan

    # Create directories
    for rel_path, kind in plan.items():
        full_path = target / rel_path
        if kind == "dir":
            full_path.mkdir(parents=True, exist_ok=True)

    # Create workspace identity (atomic)
    identity = build_workspace_identity()
    identity_path = target / WSPACE_FILE
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(identity_path, json.dumps(identity.model_dump(), indent=2))

    # Write config
    workspace_name = target.resolve(strict=False).name
    if template == "starter":
        config_content = STARTER_CONFIG.format(workspace_name=workspace_name)
    else:
        config_content = BLANK_CONFIG.format(workspace_name=workspace_name)
    _write_if_missing(target / "nexusos.toml", config_content)

    # README
    if template == "starter":
        readme_content = STARTER_README.format(workspace_name=workspace_name)
    else:
        readme_content = BLANK_README.format(workspace_name=workspace_name)
    _write_if_missing(target / "README.md", readme_content)

    # SCHEMA.md for starter
    if template == "starter":
        _write_if_missing(target / "SCHEMA.md", STARTER_SCHEMA)

    return plan


def load_workspace_identity(workspace_root: Path) -> WorkspaceIdentity | None:
    """Load workspace identity from a workspace root."""
    identity_path = workspace_root / WSPACE_FILE
    if not identity_path.is_file():
        return None
    try:
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        return WorkspaceIdentity.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return None

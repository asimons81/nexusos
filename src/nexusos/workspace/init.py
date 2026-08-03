"""Workspace initialization with blank and starter templates."""

from __future__ import annotations

import contextlib
import json
import os
import random
import string
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from nexusos import __version__
from nexusos.core.errors import (
    NonEmptyDirectoryError,
    PathSafetyError,
    TemplateError,
    WorkspaceAlreadyExistsError,
)
from nexusos.core.models import WorkspaceIdentity
from nexusos.core.path_safety import (
    check_nesting,
    check_symlink_escape,
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
# CLI flags override environment variables where supported.

[workspace]
name = "{workspace_name}"

[files]
include = ["**/*.md", "**/*.txt"]
exclude = [
    "**/.nexusos/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.git/**",
    "**/.direnv/**",
]

[limits]
max_file_size_bytes = 10_485_760
symlink_policy = "ignore"

[indexing]
chunk_max_chars = 2400
chunk_overlap_chars = 200
default_collection = "inbox"

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

[mcp]
enabled = true
transport = "stdio"

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
    "**/.direnv/**",
]

[limits]
max_file_size_bytes = 10_485_760
symlink_policy = "ignore"

[indexing]
chunk_max_chars = 2400
chunk_overlap_chars = 200
default_collection = "inbox"

[search]
max_results = 50
snippet_length = 200

[server]
host = "127.0.0.1"
port = 8765

[mcp]
enabled = true
transport = "stdio"

[lint]
max_file_size_bytes = 5_242_880
warn_empty_docs = true
"""

STARTER_README = """# {workspace_name}

This is a NexusOS knowledge workspace. Your Markdown and text files are the source of
truth; generated state lives inside `.nexusos/` and can be rebuilt.

## Getting started

1. Add Markdown or text files under `wiki/`, `raw/`, `inbox/`, `ops/`, `mocs/`, or
   `journal/`.
2. Run `nexusos doctor` to validate the workspace.
3. Run `nexusos index` to build or refresh derived state.
4. Run `nexusos search "your query"` to retrieve source-aware results.
5. Run `nexusos lint --workspace .` to check links, frontmatter, structure, and staleness.

## Agent access through MCP

Start the local stdio server with:

```bash
nexusos mcp --workspace .
```

Retrieval tools are read-only. The MCP `index` tool writes only generated state inside
`.nexusos/`.

## Directory layout

- `inbox/`: unprocessed items waiting to be classified
- `raw/`: source documents such as articles, conversations, notes, and transcripts
- `wiki/`: structured concepts, entities, projects, and saved queries
- `ops/`: decisions, standard operating procedures, and workflows
- `mocs/`: maps of content and topical indexes
- `journal/`: timestamped entries
- `.nexusos/`: generated workspace identity and index state

## Configuration

See `nexusos.toml` for workspace settings. Use `nexusos config show --effective` to inspect
resolved values.

NexusOS v0.1 is designed for a local, single-user workspace. Keep HTTP transports bound
to loopback unless you provide an appropriate external security layer.
"""

BLANK_README = """# {workspace_name}

This is a NexusOS knowledge workspace. Add Markdown or text files, then run:

```bash
nexusos doctor
nexusos index
nexusos status
nexusos search "your query"
```

Generated state lives inside `.nexusos/`. Source files remain the system of record.
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
    """Write a file atomically using a private temp file + rename.

    The temp file is created with O_EXCL semantics in the same directory as
    the target (so the rename is atomic) using a random name, so a pre-staged
    symlink at a predictable temp path can never be followed (F-01). The
    final ``os.replace`` swaps the directory entry itself and never follows a
    symlink at the target path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Best-effort cleanup of the private temp file.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


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

    # F-01 guard: refuse to adopt a workspace whose .nexusos/ directory is a
    # symlink or already contains pre-existing entries (e.g. a staged
    # workspace.json.tmp symlink). Writing into such a directory could
    # redirect the identity write to an arbitrary file.
    if adopt:
        nexusos_dir = target / ".nexusos"
        if nexusos_dir.is_symlink():
            raise PathSafetyError(
                f"Refusing to adopt {target}: .nexusos/ is a symlink",
                exit_code=2,
            )
        if nexusos_dir.exists() and not nexusos_dir.is_dir():
            raise PathSafetyError(
                f"Refusing to adopt {target}: .nexusos/ is not a directory",
                exit_code=2,
            )
        if nexusos_dir.is_dir():
            preexisting = list(nexusos_dir.iterdir())
            if preexisting:
                raise PathSafetyError(
                    f"Refusing to adopt {target}: .nexusos/ already contains "
                    f"{len(preexisting)} item(s); remove it or initialize a fresh "
                    "workspace",
                    exit_code=2,
                )
        # F-07 guard: an adopted tree must not contain symlinks that escape
        # the workspace boundary. check_symlink_escape raises
        # SymlinkEscapeError on the first escape, which is exactly the
        # boundary guarantee adopted workspaces inherit from the security
        # model (symlink escape detection).
        check_symlink_escape(target, target)

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

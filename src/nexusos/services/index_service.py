"""Service layer for index operations."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from nexusos.core.config import load_config_effective
from nexusos.indexing.indexer import run_index
from nexusos.indexing.models import IndexRunRecord


def index_workspace(
    workspace_root: Path,
    *,
    full: bool = False,
    dry_run: bool = False,
) -> IndexRunRecord:
    """Index a workspace from its configuration.

    Args:
        workspace_root: Resolved workspace root.
        full: Full rebuild.
        dry_run: Discovery only, no writes.

    Returns the completed index-run record.
    """
    config = load_config_effective(workspace_root)
    return run_index(workspace_root, config, full=full, dry_run=dry_run)

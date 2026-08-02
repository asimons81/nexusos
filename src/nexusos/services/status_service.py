"""Service layer for workspace status."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import Any

from nexusos import __version__
from nexusos.core.config import load_config_effective
from nexusos.discovery.scanner import scan_workspace
from nexusos.indexing.indexer import _config_fingerprint
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.schema import SCHEMA_VERSION
from nexusos.workspace.init import load_workspace_identity


def get_status(workspace_root: Path) -> dict[str, Any]:
    """Compute workspace index status without modifying anything.

    Returns a JSON-serializable status dict.
    """
    identity = load_workspace_identity(workspace_root)
    if identity is None:
        return {
            "status": "uninitialized",
            "read_only": True,
            "server_version": __version__,
            "config_schema_version": 1,
            "index_schema_version": SCHEMA_VERSION,
            "workspace_id": None,
            "document_count": 0,
            "chunk_count": 0,
            "heading_count": 0,
            "resolved_link_count": 0,
            "unresolved_link_count": 0,
            "ambiguous_link_count": 0,
            "last_successful_index_at": None,
            "last_index_run_id": None,
            "stale": True,
            "stale_reasons": ["no workspace"],
        }

    try:
        config = load_config_effective(workspace_root)
    except Exception:
        return {
            "status": "error",
            "read_only": True,
            "server_version": __version__,
            "config_schema_version": 1,
            "index_schema_version": SCHEMA_VERSION,
            "workspace_id": identity.workspace_id,
            "document_count": 0,
            "chunk_count": 0,
            "heading_count": 0,
            "resolved_link_count": 0,
            "unresolved_link_count": 0,
            "ambiguous_link_count": 0,
            "last_successful_index_at": None,
            "last_index_run_id": None,
            "stale": True,
            "stale_reasons": ["config load error"],
        }

    stale_reasons: list[str] = []
    db_exists = (workspace_root / ".nexusos" / "index.sqlite3").is_file()

    if not db_exists:
        return {
            "status": "uninitialized",
            "read_only": True,
            "server_version": __version__,
            "config_schema_version": 1,
            "index_schema_version": SCHEMA_VERSION,
            "workspace_id": identity.workspace_id,
            "document_count": 0,
            "chunk_count": 0,
            "heading_count": 0,
            "resolved_link_count": 0,
            "unresolved_link_count": 0,
            "ambiguous_link_count": 0,
            "last_successful_index_at": None,
            "last_index_run_id": None,
            "stale": True,
            "stale_reasons": ["no index database"],
        }

    # Open database read-only (no create_parent!)
    kernel = IndexKernel(workspace_root)
    try:
        kernel.open(create_parent=False, read_only=True)
    except Exception as exc:
        return {
            "status": "error",
            "read_only": True,
            "server_version": __version__,
            "config_schema_version": 1,
            "index_schema_version": SCHEMA_VERSION,
            "workspace_id": identity.workspace_id,
            "document_count": 0,
            "chunk_count": 0,
            "heading_count": 0,
            "resolved_link_count": 0,
            "unresolved_link_count": 0,
            "ambiguous_link_count": 0,
            "last_successful_index_at": None,
            "last_index_run_id": None,
            "stale": True,
            "stale_reasons": [f"database error: {exc}"],
        }

    try:
        # Check workspace ID match
        db_ws_id = kernel.get_meta("workspace_id")
        if db_ws_id != identity.workspace_id:
            stale_reasons.append("workspace ID mismatch")

        # Check config fingerprint
        current_fingerprint = _config_fingerprint(config)
        stored_fingerprint = kernel.get_meta("config_fingerprint")
        if stored_fingerprint and stored_fingerprint != current_fingerprint:
            stale_reasons.append("config fingerprint changed")

        # Check last successful run
        last_successful = kernel.get_meta("last_successful_index_at")
        last_run_id = kernel.get_meta("last_index_run_id")

        if last_successful is None:
            stale_reasons.append("no successful index run")

        # Lightweight discovery to check for changes
        discovery = scan_workspace(workspace_root, config)
        existing_sigs = {s.normalized_path: s for s in kernel.list_document_signatures()}

        existing_norm = set(existing_sigs.keys())
        current_norm = {f.normalized_path for f in discovery.files}

        if current_norm != existing_norm:
            stale_reasons.append("source files changed (additions, deletions)")
        else:
            # Content-only edits keep the path set identical. Compare the
            # discovered mtime/size against the stored signature, mirroring
            # the indexer's fast-path change detection, so an in-place edit
            # is reported stale.
            for f in discovery.files:
                sig = existing_sigs.get(f.normalized_path)
                if sig is not None and (
                    sig.mtime_ns != f.mtime_ns or sig.size_bytes != f.size_bytes
                ):
                    stale_reasons.append("source files changed")
                    break

        counts = kernel.counts()

        status = "ready"
        if stale_reasons:
            # Check if it's just config fingerprint (benign change)
            if stale_reasons == ["config fingerprint changed"] and last_successful:
                status = "ready" if current_norm == existing_norm else "stale"
            else:
                status = "stale"

        if "database error" in " ".join(stale_reasons):
            status = "error"

        return {
            "status": status,
            "read_only": True,
            "server_version": __version__,
            "config_schema_version": 1,
            "index_schema_version": SCHEMA_VERSION,
            "workspace_id": identity.workspace_id,
            "document_count": counts.document_count,
            "chunk_count": counts.chunk_count,
            "heading_count": counts.heading_count,
            "resolved_link_count": counts.resolved_link_count,
            "unresolved_link_count": counts.unresolved_link_count,
            "ambiguous_link_count": counts.ambiguous_link_count,
            "last_successful_index_at": last_successful,
            "last_index_run_id": last_run_id,
            "stale": bool(stale_reasons),
            "stale_reasons": stale_reasons,
        }

    finally:
        kernel.close()

"""Indexer: orchestrates discovery → parsing → chunking → persistence.

The main entry point is :func:`run_index`, which performs a full incremental
or full-rebuild index pass.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence  # noqa: TC003
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from nexusos.core.models import NexusOSConfig
from nexusos.discovery.scanner import scan_workspace
from nexusos.indexing.chunker import ChunkCandidate, chunk_document
from nexusos.indexing.graph import resolve_links
from nexusos.indexing.ids import chunk_id as make_chunk_id
from nexusos.indexing.ids import document_id as make_document_id
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import (
    IndexedChunk,
    IndexedDocument,
    IndexedHeading,
    IndexedLink,
    IndexRunRecord,
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _config_fingerprint(config: NexusOSConfig) -> str:
    """Deterministic fingerprint of discovery/parsing/chunking config fields."""
    fields = {
        "include_patterns": sorted(config.include_patterns),
        "exclude_patterns": sorted(config.exclude_patterns),
        "collection_mappings": dict(sorted(config.collection_mappings.items())),
        "default_collection": config.default_collection,
        "max_file_size_bytes": config.max_file_size_bytes,
        "symlink_policy": config.symlink_policy,
        "chunk_max_chars": config.chunk_max_chars,
        "chunk_overlap_chars": config.chunk_overlap_chars,
    }
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_index(
    workspace_root: Path,
    config: NexusOSConfig,
    *,
    full: bool = False,
    dry_run: bool = False,
) -> IndexRunRecord:
    """Run an index pass and return the completed run record.

    Args:
        workspace_root: Resolved workspace root path.
        config: Loaded, effective configuration.
        full: If True, reparse every file (not just changed ones).
        dry_run: If True, discover only — no database writes.
    """
    kernel = IndexKernel(workspace_root)
    mode = "full" if full else "incremental"

    lock_run_id: str | None = None

    if dry_run:
        # Dry run: discover only, no kernel open, no lock
        discovery = scan_workspace(workspace_root, config)
        return IndexRunRecord(
            run_id="nxo_run_dry",
            started_at=_iso_now(),
            mode=f"{mode}-dry",
            files_seen=len(discovery.files),
            success=True,
        )

    # Open kernel and acquire lock
    kernel.open(create_parent=True)
    run_record = kernel.begin_run(mode=mode)
    lock_run_id = run_record.run_id

    try:
        with kernel.write_lock(lock_run_id=lock_run_id), kernel.transaction():
            completed = _index_pass(
                kernel, workspace_root, config, full=full, run_record=run_record
            )
    except Exception:
        # Rollback is handled by transaction context manager
        kernel.complete_run(
            run_record,
            success=False,
            error_summary="index pass failed",
            error_count=1,
        )
        kernel.close()
        raise

    kernel.close()
    return completed


def _index_pass(
    kernel: IndexKernel,
    workspace_root: Path,
    config: NexusOSConfig,
    *,
    full: bool,
    run_record: IndexRunRecord,
) -> IndexRunRecord:
    """Core indexing logic inside a transaction and lock."""
    discovery = scan_workspace(workspace_root, config)

    # Record config fingerprint
    fingerprint = _config_fingerprint(config)
    kernel.set_meta("config_fingerprint", fingerprint)

    # Determine what changed
    current_paths: dict[str, DiscoveredFile] = {}
    for f in discovery.files:
        current_paths[f.normalized_path] = f

    # Get existing documents from the index
    existing = kernel._db.list_documents()
    existing_by_path: dict[str, str] = {}  # normalized → document_id
    for c in existing:
        existing_by_path[c.normalized_path] = c.document_id

    current_normalized = set(current_paths.keys())
    existing_normalized = set(existing_by_path.keys())

    # Added: in current but not existing
    added_paths = current_normalized - existing_normalized
    # Deleted: in existing but not current
    deleted_paths = existing_normalized - current_normalized
    # Common: check for changes
    common_paths = current_normalized & existing_normalized

    changed_paths: set[str] = set()
    unchanged_paths: set[str] = set()

    if full:
        changed_paths = common_paths
    else:
        for np in common_paths:
            discovered = current_paths[np]
            stored = kernel.get_document(np)
            if stored is None:
                changed_paths.add(np)
                continue
            # Fast-path: check mtime and size
            if stored.mtime_ns != discovered.mtime_ns or stored.size_bytes != discovered.size_bytes:
                changed_paths.add(np)
            else:
                unchanged_paths.add(np)

    from nexusos.discovery.models import DiscoveredFile
    from nexusos.parsing.markdown import parse_markdown
    from nexusos.parsing.models import ParsedDocument
    from nexusos.parsing.plaintext import parse_plaintext

    # Parse and index added + changed files
    parsed_docs: dict[str, ParsedDocument] = {}
    failed: int = 0

    for np in sorted(added_paths | changed_paths):
        try:
            discovered = current_paths[np]
            file_path = workspace_root / discovered.relative_path
            source_text = file_path.read_text(encoding="utf-8")
        except Exception:
            failed += 1
            continue

        try:
            if discovered.file_type == "plaintext":
                parsed = parse_plaintext(discovered, source_text)
            else:
                parsed = parse_markdown(discovered, source_text)
            parsed_docs[np] = parsed
        except Exception:
            failed += 1
            continue

    # Convert parsed documents to IndexedDocuments and persist
    all_headings: dict[str, list[IndexedHeading]] = {}
    all_chunks: dict[str, list[ChunkCandidate]] = {}

    for np in sorted(parsed_docs.keys()):
        parsed = parsed_docs[np]
        ws_id = kernel.workspace_id
        doc_id = make_document_id(ws_id, parsed.normalized_path)

        # Headings
        ihs: list[IndexedHeading] = []
        for h in parsed.headings:
            hp = _build_path_for_ordinal(parsed.headings, h.ordinal)
            ihs.append(
                IndexedHeading(
                    ordinal=h.ordinal,
                    level=h.level,
                    text=h.text,
                    normalized_text=h.normalized_text,
                    line=h.line,
                    heading_path=hp,
                )
            )
        all_headings[doc_id] = ihs

        # Chunks
        chunk_candidates = chunk_document(
            parsed,
            chunk_max_chars=config.chunk_max_chars,
            chunk_overlap_chars=config.chunk_overlap_chars,
        )
        all_chunks[doc_id] = chunk_candidates

        # Links
        ilinks: list[IndexedLink] = []
        for wl in parsed.wikilinks:
            ilinks.append(
                IndexedLink(
                    source_line=wl.source_line,
                    raw_target=wl.raw_target,
                    target_slug=wl.target_slug,
                    target_heading=wl.target_heading,
                    label=wl.label,
                )
            )

        # Build and upsert IndexedDocument
        chunks_for_doc = [
            IndexedChunk(
                chunk_id=make_chunk_id(doc_id, c.ordinal, c.content_sha256),
                document_id=doc_id,
                ordinal=c.ordinal,
                heading_path=c.heading_path,
                start_line=c.start_line,
                end_line=c.end_line,
                text=c.text,
                content_sha256=c.content_sha256,
            )
            for c in chunk_candidates
        ]

        tags = _extract_tags(parsed)

        indexed_doc = IndexedDocument(
            document_id=doc_id,
            relative_path=parsed.relative_path,
            normalized_path=parsed.normalized_path,
            collection=parsed.collection,
            title=parsed.title,
            file_type=parsed.file_type,
            authority_class=parsed.authority_class,
            created_at=parsed.created_at,
            updated_at=parsed.updated_at,
            mtime_ns=parsed.mtime_ns,
            size_bytes=parsed.size_bytes,
            content_sha256=parsed.content_sha256,
            frontmatter_json=json.dumps(parsed.frontmatter, sort_keys=True),
            indexed_at=_iso_now(),
            line_count=parsed.line_count,
            parse_warning_count=len(parsed.parse_warnings),
            headings=ihs,
            chunks=chunks_for_doc,
            wikilinks=ilinks,
            tags=tags,
        )

        kernel.upsert_document(indexed_doc)

    # Delete removed documents
    for np in sorted(deleted_paths):
        kernel.remove_document(np)

    # Resolve links: collect ALL links from ALL current documents
    # (not just added/changed ones), because adding a document can resolve
    # previously-unresolved links in unchanged documents.
    all_current_docs = kernel._db.list_documents()
    all_current_doc_ids = {c.document_id for c in all_current_docs}
    all_links_for_resolution: list[tuple[str, list[IndexedLink]]] = []
    for c in all_current_docs:
        doc = kernel.get_document(c.normalized_path)
        if doc is not None and doc.wikilinks:
            all_links_for_resolution.append((c.document_id, doc.wikilinks))

    resolved_links = resolve_links(
        kernel, all_links_for_resolution, all_document_ids=all_current_doc_ids
    )
    for doc_id, rlinks in resolved_links:
        _update_links_for_document(kernel._db, doc_id, rlinks)

    # Complete the run
    completed = kernel.complete_run(
        run_record,
        success=True,
        files_seen=len(discovery.files),
        files_added=len(added_paths),
        files_updated=len(changed_paths),
        files_unchanged=len(unchanged_paths),
        files_deleted=len(deleted_paths),
        documents_failed=failed,
        warning_count=len(discovery.warnings),
        error_count=failed,
    )
    return completed


def _build_path_for_ordinal(
    headings: Sequence[object],
    target_ordinal: int,
) -> tuple[str, ...]:
    """Build ancestor heading path for a given ordinal."""
    path: list[str] = []
    for h in headings:
        if getattr(h, "ordinal", 0) > target_ordinal:
            break
        while path:
            last_level = 0
            for ph in headings:
                if getattr(ph, "text", "") == path[-1]:
                    last_level = getattr(ph, "level", 0)
                    break
            if last_level >= getattr(h, "level", 0):
                path.pop()
            else:
                break
        path.append(getattr(h, "text", ""))
    return tuple(path)


def _update_links_for_document(
    db: Any,
    doc_id: str,
    links: list[IndexedLink],
) -> None:
    """Update link resolution state for a document's links in the DB."""
    db._execute("DELETE FROM links WHERE source_document_id = ?", (doc_id,))
    for link in links:
        db._execute(
            "INSERT INTO links ("
            "source_document_id, source_line, raw_target, target_slug, "
            "target_heading, label, target_document_id, resolved, resolution_state"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                link.source_line,
                link.raw_target,
                link.target_slug,
                link.target_heading,
                link.label,
                link.target_document_id,
                1 if link.resolved else 0,
                link.resolution_state,
            ),
        )


def _extract_tags(parsed: object) -> list[str]:
    """Extract tags from parsed document's frontmatter."""
    tags = getattr(parsed, "tags", [])
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return []

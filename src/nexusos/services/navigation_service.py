"""Service layer for content navigation: browse, read, recent, links, context.

Read-only operations over a workspace's index. Shared by the CLI commands and
the MCP server; never mutates source documents and never creates the index
database (mirrors ``status_service`` and ``search_service`` invariants).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from nexusos.core.errors import (
    AmbiguousDocumentError,
    DocumentNotFoundError,
    IndexingError,
    NavigationError,
    WorkspaceNotFoundError,
)
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import (
    DocumentCandidate,
    IncomingLink,
    IndexedDocument,
    IndexedLink,
    RecentDocument,
)
from nexusos.workspace.init import load_workspace_identity

#: Default row cap for list-style commands.
DEFAULT_LIMIT = 50
#: Default cap for ``recent``.
DEFAULT_RECENT_LIMIT = 10


# -- workspace bootstrap ------------------------------------------------------


def _open_readonly(workspace_root: Path) -> IndexKernel:
    """Open the workspace index read-only, refusing to create it.

    Raises:
        WorkspaceNotFoundError: when the directory is not a NexusOS workspace.
        IndexingError: when the workspace exists but has no index database yet.
    """
    identity = load_workspace_identity(workspace_root)
    if identity is None:
        raise WorkspaceNotFoundError(
            f"no NexusOS workspace at {workspace_root}; run `nexusos init` first",
            exit_code=2,
        )
    kernel = IndexKernel(workspace_root)
    if not kernel.index_exists():
        raise IndexingError(
            "no index database; run `nexusos index` first",
            exit_code=2,
        )
    try:
        kernel.open(create_parent=False)
    except IndexingError:
        kernel.close()
        raise
    except Exception as exc:
        kernel.close()
        raise IndexingError(f"cannot open index database: {exc}", exit_code=3) from exc
    return kernel


# -- item resolution ----------------------------------------------------------


def _resolve_candidates(
    kernel: IndexKernel,
    item: str,
) -> list[DocumentCandidate]:
    """Resolve a user-supplied item to candidate documents.

    ``item`` may be a deterministic document id (``nxo_doc_...``) or a
    path/slug. The kernel's deterministic candidate rules decide the list:
    an exact path match wins; otherwise every document whose filename stem
    matches is returned. The caller applies the final not-found/ambiguous
    decision so no arbitrary choice is made here.
    """
    stripped = item.strip()
    if not stripped:
        raise DocumentNotFoundError("item must not be empty")
    if stripped.startswith("nxo_doc_"):
        doc = kernel.get_document_by_id(stripped)
        if doc is None:
            return []
        return [
            DocumentCandidate(
                document_id=doc.document_id,
                normalized_path=doc.normalized_path,
                title=doc.title,
                collection=doc.collection,
            )
        ]
    return kernel.lookup_candidates(stripped)


def _require_unique(kernel: IndexKernel, item: str) -> IndexedDocument:
    """Resolve ``item`` to exactly one indexed document.

    Raises:
        DocumentNotFoundError: when nothing matches.
        AmbiguousDocumentError: when multiple documents match.
    """
    candidates = _resolve_candidates(kernel, item)
    if not candidates:
        raise DocumentNotFoundError(f"no document matches {item!r}")
    if len(candidates) > 1:
        paths = ", ".join(c.normalized_path for c in candidates)
        raise AmbiguousDocumentError(
            f"{item!r} is ambiguous ({len(candidates)} matches: {paths}); use a full relative path"
        )
    doc = kernel.get_document(candidates[0].normalized_path)
    if doc is None:
        raise DocumentNotFoundError(f"no document matches {item!r}")
    return doc


# -- browse -------------------------------------------------------------------


def browse_workspace(
    workspace_root: Path,
    *,
    collection: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List indexed documents (optionally filtered by collection).

    Returns a JSON-serializable dict with a ``documents`` list ordered by
    ``normalized_path`` then ``title`` (the kernel's deterministic order).
    """
    kernel = _open_readonly(workspace_root)
    try:
        docs = kernel.list_documents()
    finally:
        kernel.close()

    if collection is not None:
        docs = [c for c in docs if c.collection == collection]
    if limit is not None:
        docs = docs[:limit]

    return {
        "workspace": workspace_root.resolve(),
        "collection": collection,
        "count": len(docs),
        "documents": [
            {
                "document_id": c.document_id,
                "path": c.normalized_path,
                "title": c.title,
                "collection": c.collection,
            }
            for c in docs
        ],
    }


# -- read ---------------------------------------------------------------------


def read_document(
    workspace_root: Path,
    item: str,
    *,
    max_lines: int | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Read the content of a named document with its path.

    The content is assembled from the source-preserving chunks stored in the
    index, in chunk order. ``max_lines`` and ``max_chars`` bound the returned
    content (applied to the plain-text rendering).

    Raises:
        DocumentNotFoundError / AmbiguousDocumentError: when ``item`` cannot
            be resolved to exactly one document.
    """
    kernel = _open_readonly(workspace_root)
    try:
        doc = _require_unique(kernel, item)
        content = _render_document_content(doc)
    finally:
        kernel.close()

    truncated = False
    if max_lines is not None and max_lines > 0:
        lines = content.splitlines()
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines])
            truncated = True
    if max_chars is not None and max_chars > 0 and len(content) > max_chars:
        content = content[:max_chars]
        truncated = True

    return {
        "document_id": doc.document_id,
        "path": doc.relative_path,
        "title": doc.title,
        "collection": doc.collection,
        "content": content,
        "truncated": truncated,
    }


def _render_document_content(doc: IndexedDocument) -> str:
    """Assemble the plain-text content of a document from its chunks."""
    if not doc.chunks:
        return ""
    return "\n".join(chunk.text for chunk in doc.chunks)


# -- recent -------------------------------------------------------------------


def recent_documents(
    workspace_root: Path,
    *,
    limit: int = DEFAULT_RECENT_LIMIT,
) -> dict[str, Any]:
    """List the most recently modified documents (newest first)."""
    if limit < 1:
        raise NavigationError("limit must be a positive integer", exit_code=2)
    kernel = _open_readonly(workspace_root)
    try:
        docs = kernel.recent_documents(limit)
    finally:
        kernel.close()

    return {
        "workspace": workspace_root.resolve(),
        "limit": limit,
        "count": len(docs),
        "documents": [_recent_to_dict(d) for d in docs],
    }


def _recent_to_dict(doc: RecentDocument) -> dict[str, Any]:
    return {
        "document_id": doc.document_id,
        "path": doc.normalized_path,
        "title": doc.title,
        "collection": doc.collection,
        "mtime_ns": doc.mtime_ns,
        "mtime": _format_mtime(doc.mtime_ns),
    }


def _format_mtime(mtime_ns: int) -> str:
    """Format a nanosecond mtime as a UTC ISO-8601 timestamp."""
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=UTC).isoformat()


# -- links --------------------------------------------------------------------


def document_links(
    workspace_root: Path,
    item: str,
) -> dict[str, Any]:
    """Show outgoing and incoming wiki links for a document.

    Outgoing links come from the document's own stored wikilinks; incoming
    links are the links whose target resolves to this document. Both carry
    their resolution state so unresolved/ambiguous links are visible.
    """
    kernel = _open_readonly(workspace_root)
    try:
        doc = _require_unique(kernel, item)
        path_by_id = {c.document_id: c.normalized_path for c in kernel.list_documents()}
        incoming = kernel.incoming_links(doc.document_id)
    finally:
        kernel.close()

    return {
        "document_id": doc.document_id,
        "path": doc.relative_path,
        "title": doc.title,
        "collection": doc.collection,
        "outgoing": [_outgoing_to_dict(link, path_by_id) for link in doc.wikilinks],
        "incoming": [_incoming_to_dict(link) for link in incoming],
    }


def _outgoing_to_dict(link: IndexedLink, path_by_id: dict[str, str]) -> dict[str, Any]:
    return {
        "source_line": link.source_line,
        "raw_target": link.raw_target,
        "target_slug": link.target_slug,
        "target_heading": link.target_heading,
        "label": link.label,
        "resolution_state": link.resolution_state,
        "target_path": path_by_id.get(link.target_document_id) if link.target_document_id else None,
    }


def _incoming_to_dict(link: IncomingLink) -> dict[str, Any]:
    return {
        "source_path": link.source_path,
        "source_line": link.source_line,
        "raw_target": link.raw_target,
        "target_slug": link.target_slug,
        "resolution_state": link.resolution_state,
    }


# -- context ------------------------------------------------------------------


def document_context(
    workspace_root: Path,
    item: str,
    *,
    sibling_limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Show surrounding or related items for a document.

    Related items are computed deterministically from the index: documents in
    the same collection (siblings) and documents directly linked to or from
    the item. No LLM, no evidence scoring — pure index relations.
    """
    kernel = _open_readonly(workspace_root)
    try:
        doc = _require_unique(kernel, item)
        path_by_id = {c.document_id: c.normalized_path for c in kernel.list_documents()}
        incoming = kernel.incoming_links(doc.document_id)

        siblings = [
            c
            for c in kernel.list_documents()
            if c.collection == doc.collection and c.document_id != doc.document_id
        ][:sibling_limit]

        linked_out = [
            path_by_id[link.target_document_id]
            for link in doc.wikilinks
            if link.target_document_id and link.target_document_id in path_by_id
        ]
        linked_in = [link.source_path for link in incoming]
        linked = sorted(set(linked_out + linked_in))
    finally:
        kernel.close()

    return {
        "document_id": doc.document_id,
        "path": doc.relative_path,
        "title": doc.title,
        "collection": doc.collection,
        "headings": [{"level": h.level, "text": h.text, "line": h.line} for h in doc.headings],
        "siblings": [
            {
                "document_id": c.document_id,
                "path": c.normalized_path,
                "title": c.title,
                "collection": c.collection,
            }
            for c in siblings
        ],
        "linked": linked,
        "outgoing": [_outgoing_to_dict(link, path_by_id) for link in doc.wikilinks],
        "incoming": [_incoming_to_dict(link) for link in incoming],
    }

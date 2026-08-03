"""MCP server for NexusOS: publish the workspace index over the Model Context Protocol.

The server wraps the read-only service layer (status, search, browse, read,
recent, links, context) and the index service as MCP tools. It speaks the
protocol over stdio (``nexusos mcp`` / ``python -m nexusos.mcp``) or
loopback-only Streamable HTTP (``nexusos serve --transport streamable-http``).
Every tool returns JSON-serializable data (both as text content and
structured content), and service errors surface as clean MCP tool errors
instead of crashing the server.

Layering: this package is a top layer above ``services`` (sibling of
``cli``). It is never imported by ``core``, ``workspace``, or ``indexing``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import func_metadata
from pydantic import BaseModel, ConfigDict, Field

from nexusos import __version__
from nexusos.core.errors import NexusOSError
from nexusos.core.limits import (
    MAX_BROWSE_LIMIT,
    MAX_CONTEXT_SIBLING_LIMIT,
    MAX_RECENT_LIMIT,
    MAX_SEARCH_LIMIT,
    MAX_SEARCH_TERM_LENGTH,
    MAX_SNIPPET_TOKENS,
    MIN_LIMIT,
)
from nexusos.core.models import NexusOSConfig
from nexusos.services.index_service import index_workspace
from nexusos.services.navigation_service import (
    browse_workspace,
    document_context,
    document_links,
    read_document,
    recent_documents,
)
from nexusos.services.search_service import search_workspace
from nexusos.services.status_service import get_status

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

#: Default server title advertised in the MCP handshake.
SERVER_TITLE = "NexusOS"

#: Default row cap for list-style tools (mirrors navigation_service).
DEFAULT_LIMIT = 50
#: Default cap for ``recent``.
DEFAULT_RECENT_LIMIT = 10


class _StrictArgs(BaseModel):
    """Base class for tool argument models: reject unknown keys.

    ``model_dump_one_level`` is required by the mcp SDK when a strict
    argument model is swapped in via :func:`func_metadata` — the SDK builds
    the flat kwargs dict from this method.
    """

    model_config = ConfigDict(extra="forbid")

    def model_dump_one_level(self) -> dict[str, Any]:
        return {f.alias or n: getattr(self, n) for n, f in self.model_fields.items()}


# -- tool argument models -----------------------------------------------------


class SearchArgs(_StrictArgs):
    """Arguments for the ``search`` tool."""

    term: str = Field(max_length=MAX_SEARCH_TERM_LENGTH)
    limit: int = Field(default=DEFAULT_LIMIT, ge=MIN_LIMIT, le=MAX_SEARCH_LIMIT)
    snippet_tokens: int = Field(default=200, ge=MIN_LIMIT, le=MAX_SNIPPET_TOKENS)


class BrowseArgs(_StrictArgs):
    """Arguments for the ``browse`` tool."""

    collection: str | None = None
    limit: int | None = Field(default=None, ge=MIN_LIMIT, le=MAX_BROWSE_LIMIT)


class ReadArgs(_StrictArgs):
    """Arguments for the ``read`` tool."""

    item: str
    max_lines: int | None = None
    max_chars: int | None = None


class RecentArgs(_StrictArgs):
    """Arguments for the ``recent`` tool."""

    limit: int = Field(default=DEFAULT_RECENT_LIMIT, ge=MIN_LIMIT, le=MAX_RECENT_LIMIT)


class LinksArgs(_StrictArgs):
    """Arguments for the ``links`` tool."""

    item: str


class ContextArgs(_StrictArgs):
    """Arguments for the ``context`` tool."""

    item: str
    sibling_limit: int = Field(default=DEFAULT_LIMIT, ge=MIN_LIMIT, le=MAX_CONTEXT_SIBLING_LIMIT)


class StatusArgs(_StrictArgs):
    """Arguments for the ``status`` tool (none required)."""


class IndexArgs(_StrictArgs):
    """Arguments for the ``index`` tool."""

    full: bool = False
    dry_run: bool = False


# -- tool implementations -----------------------------------------------------


def _err(exc: NexusOSError) -> ToolError:
    """Convert a NexusOS service error into an MCP tool error."""
    return ToolError(str(exc))


def _make_tool(
    *,
    name: str,
    description: str,
    args_model: type[_StrictArgs],
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Tool:
    """Build a strict-schema MCP tool from a flat-parameter async function.

    The SDK-generated argument model is swapped for ``args_model`` so that
    extra keys are rejected by the SDK itself (``additionalProperties:
    false`` in the advertised schema) and validated against our strict model.
    """
    meta = func_metadata(fn, structured_output=True)
    # Swap the SDK-generated argument model for our strict one. The SDK calls
    # ``model_dump_one_level()`` on it when building kwargs; _StrictArgs
    # provides that method. ``cast`` silences mypy, which types arg_model as
    # ``type[ArgModelBase]``.
    meta.arg_model = cast("type[Any]", args_model)
    schema = args_model.model_json_schema(by_alias=True)
    schema["additionalProperties"] = False
    return Tool(
        fn=fn,
        name=name,
        title=None,
        description=description,
        parameters=schema,
        fn_metadata=meta,
        is_async=True,
        context_kwarg=None,
        annotations=None,
    )


def _build_search_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _search(
        term: str, limit: int = DEFAULT_LIMIT, snippet_tokens: int = 200
    ) -> dict[str, Any]:
        try:
            report = search_workspace(
                workspace_root,
                term,
                limit=limit,
                snippet_tokens=snippet_tokens,
            )
        except NexusOSError as exc:
            raise _err(exc) from exc
        return report.to_dict()

    return _make_tool(
        name="search",
        description=(
            "Full-text search over the workspace index (SQLite FTS5, "
            "prefix matching, case-insensitive). Returns ranked hits with "
            "source path, line range, and a highlighted snippet."
        ),
        args_model=SearchArgs,
        fn=_search,
    )


def _build_browse_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _browse(collection: str | None = None, limit: int | None = None) -> dict[str, Any]:
        try:
            return browse_workspace(workspace_root, collection=collection, limit=limit)
        except NexusOSError as exc:
            raise _err(exc) from exc

    return _make_tool(
        name="browse",
        description=(
            "List indexed documents (optionally filtered by collection). "
            "Returns document id, path, title, and collection in "
            "deterministic order."
        ),
        args_model=BrowseArgs,
        fn=_browse,
    )


def _build_read_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _read(
        item: str,
        max_lines: int | None = None,
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        try:
            return read_document(
                workspace_root,
                item,
                max_lines=max_lines,
                max_chars=max_chars,
            )
        except NexusOSError as exc:
            raise _err(exc) from exc

    return _make_tool(
        name="read",
        description=(
            "Read the content of an indexed document by id, relative path, "
            "or name. Returns the plain-text content plus metadata "
            "(document id, path, title, collection)."
        ),
        args_model=ReadArgs,
        fn=_read,
    )


def _build_recent_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _recent(limit: int = DEFAULT_RECENT_LIMIT) -> dict[str, Any]:
        try:
            return recent_documents(workspace_root, limit=limit)
        except NexusOSError as exc:
            raise _err(exc) from exc

    return _make_tool(
        name="recent",
        description="List the most recently modified indexed documents, newest first.",
        args_model=RecentArgs,
        fn=_recent,
    )


def _build_links_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _links(item: str) -> dict[str, Any]:
        try:
            return document_links(workspace_root, item)
        except NexusOSError as exc:
            raise _err(exc) from exc

    return _make_tool(
        name="links",
        description=(
            "Show outgoing and incoming wiki links for an indexed document, "
            "with resolution state for each link."
        ),
        args_model=LinksArgs,
        fn=_links,
    )


def _build_context_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _context(item: str, sibling_limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        try:
            return document_context(workspace_root, item, sibling_limit=sibling_limit)
        except NexusOSError as exc:
            raise _err(exc) from exc

    return _make_tool(
        name="context",
        description=(
            "Show surrounding or related items for a document: headings, "
            "siblings in the same collection, and directly linked documents."
        ),
        args_model=ContextArgs,
        fn=_context,
    )


def _build_status_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _status() -> dict[str, Any]:
        try:
            return get_status(workspace_root)
        except NexusOSError as exc:
            raise _err(exc) from exc

    return _make_tool(
        name="status",
        description=(
            "Show workspace index status: index state, document/chunk/heading "
            "counts, link counts, last successful index time, and staleness "
            "reasons. Read-only; never creates the index database."
        ),
        args_model=StatusArgs,
        fn=_status,
    )


def _build_index_tool(workspace_root: Path, config: NexusOSConfig) -> Tool:
    async def _index(full: bool = False, dry_run: bool = False) -> dict[str, Any]:
        try:
            run = index_workspace(workspace_root, full=full, dry_run=dry_run)
        except NexusOSError as exc:
            raise _err(exc) from exc
        return run.model_dump(mode="json")

    return _make_tool(
        name="index",
        description=(
            "Index (or re-index) the workspace source corpus. Runs the same "
            "incremental index pass as `nexusos index`; returns the "
            "index-run record with file counts and success flag."
        ),
        args_model=IndexArgs,
        fn=_index,
    )


# -- server assembly ----------------------------------------------------------


def build_server(
    workspace_root: Path,
    *,
    config: NexusOSConfig | None = None,
) -> MCPServer:
    """Build an MCP server bound to a NexusOS workspace.

    Args:
        workspace_root: Resolved workspace root path.
        config: Effective configuration; loaded from the workspace when None.

    Returns:
        A configured :class:`MCPServer` exposing the status, search, browse,
        read, recent, links, context, and index tools over the requested
        transport (stdio or streamable-http).
    """
    root = Path(workspace_root).resolve(strict=False)
    if config is None:
        from nexusos.core.config import load_config_effective

        config = load_config_effective(root)

    tools = [
        _build_status_tool(root, config),
        _build_search_tool(root, config),
        _build_browse_tool(root, config),
        _build_read_tool(root, config),
        _build_recent_tool(root, config),
        _build_links_tool(root, config),
        _build_context_tool(root, config),
        _build_index_tool(root, config),
    ]

    return MCPServer(
        name="nexusos",
        title=SERVER_TITLE,
        description=(
            "Local-first knowledge OS: search and navigate an indexed "
            "NexusOS workspace over the Model Context Protocol."
        ),
        version=__version__,
        instructions=(
            "This server exposes a NexusOS workspace's index. Use search "
            "for full-text retrieval, browse to list documents, read to get "
            "document content, recent for newest documents, links/context "
            "for wiki-link relations, and index to run an index pass over "
            "the source corpus."
        ),
        tools=tools,
    )

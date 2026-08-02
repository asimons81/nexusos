"""Unit tests for the NexusOS MCP server construction and tool schemas.

L1/L2 checks: the server builds with the expected tool set, every tool
advertises a strict schema (``additionalProperties: false``), argument
models reject unknown keys, and the ``index`` tool's schema mirrors the
indexer contract.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nexusos.core.models import NexusOSConfig
from nexusos.mcp.server import (
    BrowseArgs,
    ContextArgs,
    IndexArgs,
    LinksArgs,
    ReadArgs,
    RecentArgs,
    SearchArgs,
    build_server,
)

EXPECTED_TOOLS = ("search", "browse", "read", "recent", "links", "context", "index")


def _server() -> Any:
    """Build the server with an explicit default config (no filesystem)."""
    return build_server(Path("/tmp/nonexistent-ws"), config=NexusOSConfig())


def test_build_server_registers_expected_tools() -> None:
    server = _server()
    assert server.name == "nexusos"
    assert server.version == "0.1.0-alpha.1"
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == set(EXPECTED_TOOLS)


def test_build_server_tool_descriptions_nonempty() -> None:
    server = _server()
    tools = asyncio.run(server.list_tools())
    for tool in tools:
        assert tool.description, f"{tool.name} must have a description"


def test_tools_advertise_strict_schema() -> None:
    server = _server()
    tools = asyncio.run(server.list_tools())
    schemas = {t.name: t.input_schema for t in tools}
    assert set(schemas) == set(EXPECTED_TOOLS)
    for name, schema in schemas.items():
        assert schema.get("additionalProperties") is False, f"{name} must forbid extra properties"
        assert schema["type"] == "object"


def test_search_args_required_field() -> None:
    SearchArgs(term="kernel")
    try:
        SearchArgs()  # type: ignore[call-arg]
    except ValidationError:
        pass
    else:
        raise AssertionError("SearchArgs without term must fail validation")


def test_search_args_rejects_extra_key() -> None:
    try:
        SearchArgs(term="kernel", bogus=1)  # type: ignore[call-arg]
    except ValidationError:
        pass
    else:
        raise AssertionError("SearchArgs must reject unknown keys")


def test_read_args_defaults() -> None:
    args = ReadArgs(item="wiki/kernel.md")
    assert args.max_lines is None
    assert args.max_chars is None


def test_browse_args_optional() -> None:
    args = BrowseArgs()
    assert args.collection is None
    assert args.limit is None
    assert BrowseArgs(collection="wiki", limit=5).limit == 5


def test_recent_args_positive_default() -> None:
    args = RecentArgs()
    assert args.limit == 10
    assert RecentArgs(limit=3).limit == 3


def test_links_context_require_item() -> None:
    assert LinksArgs(item="notes").item == "notes"
    assert ContextArgs(item="notes", sibling_limit=20).sibling_limit == 20


def test_index_args_flags() -> None:
    args = IndexArgs()
    assert args.full is False
    assert args.dry_run is False
    assert IndexArgs(full=True).full is True
    assert IndexArgs(dry_run=True).dry_run is True


def test_arg_models_share_strict_base() -> None:
    """Every args model must be a subclass of the strict base (extra=forbid)."""
    from nexusos.mcp.server import _StrictArgs

    for model in (SearchArgs, BrowseArgs, ReadArgs, RecentArgs, LinksArgs, ContextArgs, IndexArgs):
        assert issubclass(model, _StrictArgs), f"{model.__name__} must inherit _StrictArgs"

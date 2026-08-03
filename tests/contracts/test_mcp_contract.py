"""Contract tests: MCP tool names, input schemas, bounds, and error behavior.

Locks docs/contracts.md §3. The MCP server must advertise exactly the frozen
tool set, every tool must expose a strict schema (additionalProperties:
false) with the documented bounds, and service errors must surface as MCP
tool errors rather than crashing the server.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from nexusos.core.limits import (
    MAX_BROWSE_LIMIT,
    MAX_CONTEXT_SIBLING_LIMIT,
    MAX_RECENT_LIMIT,
    MAX_SEARCH_LIMIT,
    MAX_SNIPPET_TOKENS,
    MIN_LIMIT,
)
from nexusos.core.models import NexusOSConfig
from nexusos.mcp.server import (
    BrowseArgs,
    ContextArgs,
    IndexArgs,
    ReadArgs,
    RecentArgs,
    SearchArgs,
    build_server,
)

#: The frozen tool set (docs/contracts.md §3.2).
EXPECTED_TOOLS: tuple[str, ...] = (
    "status",
    "search",
    "browse",
    "read",
    "recent",
    "links",
    "context",
    "index",
)

SERVER_NAME = "nexusos"
SERVER_TITLE = "NexusOS"


def _server() -> Any:
    return build_server(Path("/tmp/nonexistent-ws"), config=NexusOSConfig())


def _list_tools(server: Any) -> list[Any]:
    return asyncio.run(server.list_tools())


# -- tool set -----------------------------------------------------------------


def test_server_identity() -> None:
    from nexusos import __version__

    server = _server()
    assert server.name == SERVER_NAME
    assert server.version == __version__


def test_tool_set_is_frozen() -> None:
    server = _server()
    names = [t.name for t in _list_tools(server)]
    assert tuple(names) == EXPECTED_TOOLS


def test_every_tool_has_description() -> None:
    server = _server()
    for tool in _list_tools(server):
        assert tool.description, f"{tool.name} missing description"


# -- strict schemas -----------------------------------------------------------


def test_every_tool_advertises_strict_schema() -> None:
    server = _server()
    for tool in _list_tools(server):
        schema = tool.input_schema
        assert schema.get("type") == "object", f"{tool.name} not object schema"
        assert schema.get("additionalProperties") is False, (
            f"{tool.name} must forbid extra properties"
        )


def test_search_schema_bounds() -> None:
    schema = SearchArgs.model_json_schema(by_alias=True)
    props = schema["properties"]
    assert props["term"]["type"] == "string"
    assert props["limit"]["default"] == 50
    assert props["limit"]["minimum"] == MIN_LIMIT
    assert props["limit"]["maximum"] == MAX_SEARCH_LIMIT
    assert props["snippet_tokens"]["default"] == 200
    assert props["snippet_tokens"]["maximum"] == MAX_SNIPPET_TOKENS


def test_browse_schema_bounds() -> None:
    schema = BrowseArgs.model_json_schema(by_alias=True)
    props = schema["properties"]
    limit = props["limit"]
    # nullable int → bounds live inside anyOf
    assert any(part.get("maximum") == MAX_BROWSE_LIMIT for part in limit["anyOf"])


def test_recent_schema_bounds() -> None:
    schema = RecentArgs.model_json_schema(by_alias=True)
    props = schema["properties"]
    assert props["limit"]["default"] == 10
    assert props["limit"]["maximum"] == MAX_RECENT_LIMIT


def test_context_schema_bounds() -> None:
    schema = ContextArgs.model_json_schema(by_alias=True)
    props = schema["properties"]
    assert props["sibling_limit"]["default"] == 50
    assert props["sibling_limit"]["maximum"] == MAX_CONTEXT_SIBLING_LIMIT


# -- argument model validation -------------------------------------------------


def test_search_args_require_term() -> None:
    with pytest.raises(Exception):
        SearchArgs()  # type: ignore[call-arg]


def test_search_args_reject_extra_keys() -> None:
    with pytest.raises(Exception):
        SearchArgs(term="x", bogus=1)  # type: ignore[call-arg]


def test_search_args_reject_out_of_range() -> None:
    with pytest.raises(Exception):
        SearchArgs(term="x", limit=0)
    with pytest.raises(Exception):
        SearchArgs(term="x", limit=501)


def test_recent_args_reject_out_of_range() -> None:
    with pytest.raises(Exception):
        RecentArgs(limit=0)
    with pytest.raises(Exception):
        RecentArgs(limit=101)


def test_context_args_reject_out_of_range() -> None:
    with pytest.raises(Exception):
        ContextArgs(item="x", sibling_limit=0)
    with pytest.raises(Exception):
        ContextArgs(item="x", sibling_limit=101)


def test_index_args_defaults() -> None:
    args = IndexArgs()
    assert args.full is False
    assert args.dry_run is False


def test_read_args_optional_bounds() -> None:
    args = ReadArgs(item="x", max_lines=10, max_chars=100)
    assert args.max_lines == 10
    assert args.max_chars == 100


# -- error behavior (service errors surface as tool errors) ---------------------


def test_tool_error_on_missing_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing document produces an MCP tool error, not a server crash."""
    from mcp.server.mcpserver.exceptions import ToolError

    from nexusos.mcp.server import _build_read_tool
    from nexusos.workspace.init import init_workspace

    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    tool = _build_read_tool(ws, NexusOSConfig())

    with pytest.raises(ToolError):
        asyncio.run(_call_tool(tool, item="nope"))


def _call_tool(tool: Any, **kwargs: Any) -> Any:
    """Invoke an MCP tool's async fn directly with flat kwargs."""
    return tool.fn(**kwargs)

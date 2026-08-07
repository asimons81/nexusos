"""Integration tests for the NexusOS MCP server over real stdio.

Exercises the full path: initialize a synthetic workspace, index it, spawn
the real ``python -m nexusos.mcp`` subprocess, connect with the official
MCP client, and verify the handshake, tool listing, tool invocation
(valid JSON in both text and structured content), error paths, and indexing
completion over the sample corpus.

These tests use the official ``mcp`` client SDK in-process and the real
server entrypoint as a subprocess — the highest-value MCP test shape.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path  # noqa: TC003
from typing import Any

import pytest

from nexusos.workspace.init import init_workspace

pytestmark = pytest.mark.integration

_FILES = {
    "wiki/kernel.md": (
        "# Kernel Guide\n\n"
        "The NexusOS indexing kernel provides deterministic identifiers.\n"
        "Search is powered by SQLite FTS5.\n"
    ),
    "wiki/search.md": (
        "# Search\n\nThe search command queries the FTS5 index and returns ranked results.\n"
    ),
    "wiki/notes.md": "# Notes\n\nNothing about anything relevant here.\n",
}


def _make_indexed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an initialized + indexed synthetic workspace."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    for rel, text in _FILES.items():
        (ws / rel).write_text(text, encoding="utf-8")
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success
    # Blank template ships a root README.md; with the **/*.md fix it is
    # discovered and indexed alongside the corpus (previously root files
    # were silently skipped).
    assert run.files_seen == len(_FILES) + 1
    return ws


def _clean_env() -> dict[str, str]:
    """Environment for the spawned server: strip PYTHONPATH pollution."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("NEXUSOS_DENY_PATHS", None)
    return env


def _server_params(workspace: Path) -> Any:
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "nexusos.mcp", "--workspace", str(workspace)],
        env=_clean_env(),
        cwd=str(workspace),
    )


def _is_error(result: Any) -> bool:
    """Read CallToolResult.is_error across SDK field spellings."""
    value = getattr(result, "isError", None)
    if value is None:
        value = getattr(result, "is_error", None)
    return bool(value)


def _structured(result: Any) -> dict[str, Any] | None:
    """Read CallToolResult.structuredContent across SDK field spellings."""
    value = getattr(result, "structuredContent", None)
    if value is None:
        value = getattr(result, "structured_content", None)
    return value


def _text_content(result: Any) -> str:
    """Extract the concatenated text content from a CallToolResult."""
    parts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


# -- handshake ---------------------------------------------------------------


def test_mcp_handshake_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    info, tools = asyncio.run(_run_handshake(ws))
    assert info.server_info.name == "nexusos"
    assert info.server_info.version == "0.1.0"
    names = [t.name for t in tools.tools]
    assert names == ["status", "search", "browse", "read", "recent", "links", "context", "index"]


async def _run_handshake(workspace: Path) -> tuple[Any, Any]:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params(workspace)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        info = await session.initialize()
        tools = await session.list_tools()
        return info, tools


# -- tool invocation (valid JSON) --------------------------------------------


def test_search_tool_returns_valid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_search(ws, "kernel"))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert payload["query"] == "kernel"
    assert payload["total"] == 1
    hit = payload["results"][0]
    assert hit["relative_path"] == "wiki/kernel.md"
    assert hit["start_line"] == 1
    # Structured content carries the same payload.
    structured = _structured(data["result"])
    assert structured is not None
    assert structured["query"] == "kernel"


def test_search_tool_no_match_returns_empty_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_search(ws, "zzzqqq"))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert payload["total"] == 0
    assert payload["results"] == []


def test_browse_tool_returns_valid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_browse(ws))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert payload["count"] == 4
    paths = {doc["path"] for doc in payload["documents"]}
    assert paths == set(_FILES) | {"README.md"}


def test_read_tool_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_read(ws, "wiki/kernel.md"))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert payload["path"] == "wiki/kernel.md"
    assert "Kernel Guide" in payload["content"]
    structured = _structured(data["result"])
    assert structured is not None
    assert structured["title"] == "Kernel Guide"


def test_read_tool_missing_document_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_read(ws, "does-not-exist"))
    assert _is_error(data["result"])
    text = _text_content(data["result"])
    assert "no document matches" in text


def test_recent_tool_returns_valid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_recent(ws))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert payload["count"] == 4


def test_links_tool_returns_valid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_links(ws, "wiki/kernel.md"))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert "outgoing" in payload
    assert "incoming" in payload


def test_context_tool_returns_valid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_context(ws, "wiki/kernel.md"))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert "headings" in payload
    assert "siblings" in payload
    assert "linked" in payload


def test_tool_rejects_extra_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    data = asyncio.run(_call_with_extra(ws, "search", {"term": "kernel", "bogus": 1}))
    assert _is_error(data["result"])


# -- indexing completion ------------------------------------------------------


def test_index_tool_indexes_sample_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws2"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    for rel, text in _FILES.items():
        (ws / rel).write_text(text, encoding="utf-8")

    # No index yet: read-only tools report an error, but the index tool works.
    data = asyncio.run(_call_index(ws, full=False))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert payload["success"] is True
    assert payload["files_seen"] == len(_FILES) + 1  # corpus + root README.md
    assert payload["files_added"] == len(_FILES) + 1
    structured = _structured(data["result"])
    assert structured is not None
    assert structured["files_seen"] == len(_FILES) + 1

    # After indexing, search finds the corpus.
    search_data = asyncio.run(_call_search(ws, "kernel"))
    assert not _is_error(search_data["result"])
    search_payload = json.loads(_text_content(search_data["result"]))
    assert search_payload["total"] >= 1


def test_index_tool_dry_run_creates_no_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws3"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    (ws / "wiki" / "a.md").write_text("# A\n\nBody.\n", encoding="utf-8")

    data = asyncio.run(_call_index(ws, dry_run=True))
    assert not _is_error(data["result"])
    payload = json.loads(_text_content(data["result"]))
    assert payload["success"] is True
    assert payload["files_seen"] == 2  # wiki/a.md + root README.md
    assert not (ws / ".nexusos" / "index.sqlite3").exists()


# -- client helpers -----------------------------------------------------------


async def _call_tool(workspace: Path, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params(workspace)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
        return {"result": result}


async def _call_search(workspace: Path, term: str) -> dict[str, Any]:
    return await _call_tool(workspace, "search", {"term": term})


async def _call_browse(workspace: Path) -> dict[str, Any]:
    return await _call_tool(workspace, "browse", {})


async def _call_read(workspace: Path, item: str) -> dict[str, Any]:
    return await _call_tool(workspace, "read", {"item": item})


async def _call_recent(workspace: Path) -> dict[str, Any]:
    return await _call_tool(workspace, "recent", {})


async def _call_links(workspace: Path, item: str) -> dict[str, Any]:
    return await _call_tool(workspace, "links", {"item": item})


async def _call_context(workspace: Path, item: str) -> dict[str, Any]:
    return await _call_tool(workspace, "context", {"item": item})


async def _call_index(
    workspace: Path, *, full: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    return await _call_tool(workspace, "index", {"full": full, "dry_run": dry_run})


async def _call_with_extra(workspace: Path, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return await _call_tool(workspace, name, arguments)

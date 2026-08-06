"""Integration tests for the NexusOS MCP server over Streamable HTTP (RC-03).

Spawns the real MCP server bound to a loopback ephemeral port and connects
with the official MCP Python SDK's streamable-http client — the documented
``nexusos serve --transport streamable-http`` protocol surface (endpoint
``/mcp``). Verifies the release-candidate protocol contract from ROADMAP
RC-03 / docs/mcp.md:

- server startup and handshake
- tool discovery (8 tools, stable order)
- strict input schemas (``additionalProperties: false``)
- ``status``, ``search``, ``read``, ``context``, and ``index`` behavior
- source immutability across retrieval calls

These are protocol-behavior checks; they do not promise every client UI or
client-specific configuration format.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
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

_EXPECTED_TOOLS = ["status", "search", "browse", "read", "recent", "links", "context", "index"]


def _clean_env() -> dict[str, str]:
    """Environment for the spawned server: strip PYTHONPATH pollution."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("NEXUSOS_DENY_PATHS", None)
    return env


def _free_port() -> int:
    """Return a currently-free loopback TCP port (small race, fine for tests)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 20.0) -> None:
    """Poll until the MCP streamable-http endpoint accepts TCP connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"server did not listen on 127.0.0.1:{port} within {timeout}s")


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
    assert run.files_seen == len(_FILES) + 1  # corpus + root README.md
    return ws


@pytest.fixture
def http_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Spawn the real MCP streamable-http server on an ephemeral port.

    Uses ``python -m nexusos.mcp`` with environment transport overrides
    (the documented equivalent of ``nexusos serve --transport
    streamable-http``); the installed-artifact validation in the release
    manifest exercises the CLI form on a real port.
    """
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    port = _free_port()
    env = _clean_env()
    env["NEXUSOS_MCP_TRANSPORT"] = "streamable-http"
    env["NEXUSOS_SERVER_HOST"] = "127.0.0.1"
    env["NEXUSOS_SERVER_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "nexusos.mcp", "--workspace", str(ws)],
        env=env,
        cwd=str(ws),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(port)
        yield {"url": f"http://127.0.0.1:{port}/mcp", "workspace": ws, "proc": proc}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _is_error(result: Any) -> bool:
    value = getattr(result, "isError", None)
    if value is None:
        value = getattr(result, "is_error", None)
    return bool(value)


def _structured(result: Any) -> dict[str, Any] | None:
    value = getattr(result, "structuredContent", None)
    if value is None:
        value = getattr(result, "structured_content", None)
    return value


def _text_content(result: Any) -> str:
    parts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


async def _session_calls(url: str, fn: Any) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with (
        streamable_http_client(url) as (read, write),
        ClientSession(read, write) as session,
    ):
        return await fn(session)


def test_streamable_http_handshake_and_tool_discovery(
    http_server: dict[str, Any],
) -> None:
    async def _run(session: Any) -> dict[str, Any]:
        info = await session.initialize()
        tools = await session.list_tools()
        return {
            "name": info.server_info.name,
            "version": info.server_info.version,
            "tools": [t.name for t in tools.tools],
        }

    data = asyncio.run(_session_calls(http_server["url"], _run))
    assert data["name"] == "nexusos"
    assert data["version"] == "0.1.0-alpha.3"
    assert data["tools"] == _EXPECTED_TOOLS


def test_streamable_http_strict_schemas(http_server: dict[str, Any]) -> None:
    """Advertised tool schemas are strict: additionalProperties false and
    required arguments present for the tools that need them."""

    async def _run(session: Any) -> list[dict[str, Any]]:
        await session.initialize()
        tools = await session.list_tools()
        return [
            {
                "name": t.name,
                "schema": t.input_schema,
            }
            for t in tools.tools
        ]

    schemas = asyncio.run(_session_calls(http_server["url"], _run))
    by_name = {s["name"]: s["schema"] for s in schemas}
    assert set(by_name) == set(_EXPECTED_TOOLS)
    for name, schema in by_name.items():
        assert schema.get("additionalProperties") is False, f"{name} not strict"
        assert "type" in schema
        assert schema["type"] == "object"
    # Required args must be advertised so clients can build valid calls.
    assert "term" in by_name["search"].get("required", [])
    assert "item" in by_name["read"].get("required", [])
    assert "item" in by_name["context"].get("required", [])
    assert "item" in by_name["links"].get("required", [])


def test_streamable_http_status_search_read_context(
    http_server: dict[str, Any],
) -> None:
    async def _run(session: Any) -> dict[str, Any]:
        await session.initialize()
        status = await session.call_tool("status", {})
        search = await session.call_tool("search", {"term": "kernel"})
        read = await session.call_tool("read", {"item": "wiki/kernel.md"})
        context = await session.call_tool("context", {"item": "wiki/kernel.md"})
        return {
            "status": status,
            "search": search,
            "read": read,
            "context": context,
        }

    data = asyncio.run(_session_calls(http_server["url"], _run))

    assert not _is_error(data["status"])
    status_payload = json.loads(_text_content(data["status"]))
    assert status_payload["status"] == "ready"
    assert status_payload["read_only"] is True
    assert status_payload["server_version"] == "0.1.0-alpha.3"
    assert status_payload["index_schema_version"] == 2

    assert not _is_error(data["search"])
    search_payload = json.loads(_text_content(data["search"]))
    assert search_payload["query"] == "kernel"
    assert search_payload["total"] == 1
    hit = search_payload["results"][0]
    assert hit["relative_path"] == "wiki/kernel.md"
    assert hit["start_line"] == 1

    assert not _is_error(data["read"])
    read_payload = json.loads(_text_content(data["read"]))
    assert read_payload["path"] == "wiki/kernel.md"
    assert "Kernel Guide" in read_payload["content"]
    structured = _structured(data["read"])
    assert structured is not None
    assert structured["title"] == "Kernel Guide"

    assert not _is_error(data["context"])
    context_payload = json.loads(_text_content(data["context"]))
    assert "headings" in context_payload
    assert "siblings" in context_payload
    assert "linked" in context_payload


def test_streamable_http_strict_schema_rejects_extra_argument(
    http_server: dict[str, Any],
) -> None:
    async def _run(session: Any) -> Any:
        await session.initialize()
        return await session.call_tool("search", {"term": "kernel", "bogus": 1})

    result = asyncio.run(_session_calls(http_server["url"], _run))
    assert _is_error(result)


def test_streamable_http_index_tool_and_source_immutability(
    http_server: dict[str, Any],
) -> None:
    """The index tool mutates derived state only; source bytes are untouched
    by retrieval and indexing over the HTTP surface."""
    ws = http_server["workspace"]
    before = {
        rel.relative_to(ws).as_posix(): rel.read_bytes()
        for rel in ws.rglob("*")
        if rel.is_file() and ".nexusos" not in rel.parts
    }

    async def _run(session: Any) -> dict[str, Any]:
        await session.initialize()
        index = await session.call_tool("index", {"full": True})
        search = await session.call_tool("search", {"term": "notes"})
        return {"index": index, "search": search}

    data = asyncio.run(_session_calls(http_server["url"], _run))
    assert not _is_error(data["index"])
    index_payload = json.loads(_text_content(data["index"]))
    assert index_payload["success"] is True
    assert index_payload["files_seen"] == len(_FILES) + 1

    assert not _is_error(data["search"])
    search_payload = json.loads(_text_content(data["search"]))
    assert search_payload["total"] >= 1

    after = {
        rel.relative_to(ws).as_posix(): rel.read_bytes()
        for rel in ws.rglob("*")
        if rel.is_file() and ".nexusos" not in rel.parts
    }
    assert after == before

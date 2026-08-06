"""Raw JSON-RPC client compatibility test over Streamable HTTP (RC-03).

A second representative client: this test speaks the MCP protocol directly
over the Streamable HTTP endpoint with stdlib ``urllib`` and no MCP SDK
sugar. It exercises the same documented contract as the official SDK client
in ``test_mcp_streamable_http.py`` — initialize handshake, tool discovery,
strict schemas, and tool calls — and thereby proves the endpoint is
protocol-conformant, not merely compatible with one client library.

The raw client implements the Streamable HTTP subset required by the spec:
- POST to the endpoint with ``Accept: application/json, text/event-stream``
- capture and replay ``Mcp-Session-Id``
- accept either a single JSON response or an SSE ``data:`` frame
- send the ``notifications/initialized`` notification after initialize
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
    "wiki/notes.md": "# Notes\n\nNothing about anything relevant here.\n",
}

_PROTOCOL_VERSION = "2025-11-25"


class RawStreamableClient:
    """Minimal MCP Streamable HTTP client using only stdlib."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.session_id: str | None = None
        self._next_id = 1

    def _post(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            content_type = exc.headers.get("Content-Type", "")
            if exc.code == 202:
                # Notification accepted: no body expected.
                return exc.code, {}
        return self._decode(raw, content_type)

    def _decode(self, raw: bytes, content_type: str) -> tuple[int, dict[str, Any]]:
        if "text/event-stream" in content_type:
            # SSE frames: find the first `data:` line with a JSON payload.
            for line in raw.decode("utf-8", errors="replace").splitlines():
                if line.startswith("data:"):
                    return 200, json.loads(line[5:].strip())
            raise AssertionError(f"SSE response contained no data frame: {raw!r}")
        if not raw:
            return 200, {}
        return 200, json.loads(raw.decode("utf-8"))

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self._next_id += 1
        _, response = self._post(payload)
        if "error" in response:
            raise AssertionError(f"JSON-RPC error for {method}: {response['error']}")
        return response.get("result", {})

    def notify(self, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._post(payload)

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "nexusos-raw-client", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        return self.request("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("NEXUSOS_DENY_PATHS", None)
    return env


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"server did not listen on 127.0.0.1:{port} within {timeout}s")


@pytest.fixture
def raw_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Spawn the real MCP streamable-http server for raw-protocol probing."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    for rel, text in _FILES.items():
        (ws / rel).write_text(text, encoding="utf-8")
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success

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
        yield {"url": f"http://127.0.0.1:{port}/mcp", "workspace": ws}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_raw_initialize_and_tool_discovery(raw_server: dict[str, Any]) -> None:
    client = RawStreamableClient(raw_server["url"])
    info = client.initialize()
    assert info["serverInfo"]["name"] == "nexusos"
    assert info["serverInfo"]["version"] == "0.1.0-rc.1"
    assert info["protocolVersion"] == _PROTOCOL_VERSION

    tools = client.list_tools()
    names = [t["name"] for t in tools]
    assert names == ["status", "search", "browse", "read", "recent", "links", "context", "index"]
    # Every advertised schema is strict.
    for tool in tools:
        assert tool["inputSchema"].get("additionalProperties") is False


def test_raw_status_and_search(raw_server: dict[str, Any]) -> None:
    client = RawStreamableClient(raw_server["url"])
    client.initialize()

    status = client.call_tool("status", {})
    assert status["isError"] is False
    payload = json.loads(status["content"][0]["text"])
    assert payload["status"] == "ready"
    assert payload["read_only"] is True

    search = client.call_tool("search", {"term": "kernel"})
    assert search["isError"] is False
    search_payload = json.loads(search["content"][0]["text"])
    assert search_payload["total"] == 1
    assert search_payload["results"][0]["relative_path"] == "wiki/kernel.md"

    # Strict schema: extra arguments are rejected over the raw path too.
    rejected = client.call_tool("search", {"term": "kernel", "bogus": 1})
    assert rejected["isError"] is True


def test_raw_read_and_structured_content(raw_server: dict[str, Any]) -> None:
    client = RawStreamableClient(raw_server["url"])
    client.initialize()

    read = client.call_tool("read", {"item": "wiki/kernel.md"})
    assert read["isError"] is False
    text_payload = json.loads(read["content"][0]["text"])
    assert text_payload["path"] == "wiki/kernel.md"
    assert "Kernel Guide" in text_payload["content"]
    assert read["structuredContent"]["title"] == "Kernel Guide"


def test_raw_notification_does_not_break_session(raw_server: dict[str, Any]) -> None:
    """A JSON-RPC notification must not disturb the session; follow-up
    requests still work (session affinity across POSTs)."""
    client = RawStreamableClient(raw_server["url"])
    client.initialize()
    client.notify("notifications/initialized", {})
    # List tools twice: proves the session survives and request ids advance.
    first = client.list_tools()
    second = client.list_tools()
    assert [t["name"] for t in first] == [t["name"] for t in second]
    assert len(first) == 8

"""Adversarial release security tests for A3-07.

Covers the A3-07 acceptance criteria and findings from the adversarial
security release review:

- F-09: index lock file is owner-only (0o600), not world-readable
- F-10: the API token is NOT embedded in the served root page on
  non-loopback binds (the page is unauthenticated)
- F-11: source immutability across CLI, HTTP, and MCP stdio retrieval paths
  (byte-for-byte; the A3-07 acceptance criterion)
- F-12: index SQLite database files are owner-only (0o600)
- F-13: search term length is bounded consistently (CLI service + MCP schema)
- HTTP path traversal on /api/documents/... and /ui/... is rejected
- MCP stdio retrieval leaves source bytes untouched
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path  # noqa: TC003
from typing import cast

import pytest

from nexusos.core.limits import MAX_SEARCH_TERM_LENGTH
from nexusos.workspace.init import init_workspace

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_indexed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an initialized + indexed synthetic workspace with source files."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir()
    (ws / "wiki" / "alpha.md").write_text(
        "# Alpha\n\nSecret material that must never change.\n\nSee [[beta]].\n",
        encoding="utf-8",
    )
    (ws / "wiki" / "beta.md").write_text(
        "# Beta\n\nLinked from alpha. [[alpha]]\n", encoding="utf-8"
    )
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success
    return ws


def _source_snapshot(ws: Path) -> dict[str, bytes]:
    """Byte-for-byte snapshot of all source files (excluding .nexusos/)."""
    snapshot: dict[str, bytes] = {}
    for rel in sorted(ws.rglob("*")):
        if rel.is_file() and ".nexusos" not in rel.parts:
            snapshot[rel.relative_to(ws).as_posix()] = rel.read_bytes()
    return snapshot


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# F-09 — index lock file permissions
# ---------------------------------------------------------------------------


def test_f09_index_lock_file_is_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    from nexusos.indexing.lock import IndexLock

    lock = IndexLock(ws / ".nexusos" / "index.lock")
    lock.acquire()
    try:
        assert lock.lock_path.is_file()
        assert _mode(lock.lock_path) == 0o600
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# F-10 — token not embedded in root page on non-loopback binds
# ---------------------------------------------------------------------------


def _request(
    port: int,
    path: str,
    *,
    host: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
        for key, value in (headers or {}).items():
            conn.putheader(key, value)
        conn.endheaders()
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


class _ServerHarness:
    """Start a serve server on an ephemeral port for the duration of a test."""

    def __init__(self, workspace: Path, host: str = "127.0.0.1") -> None:
        import threading

        from nexusos.services.serve_service import create_server

        self.server = create_server(workspace, host=host, port=0)
        self.token = self.server.nexusos_token
        self._thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()
        _host, self.port = self.server.server_address[:2]

    def __enter__(self) -> _ServerHarness:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)


def test_f10_root_page_omits_token_on_non_loopback_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a non-loopback bind the unauthenticated root page must not leak the token."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    try:
        with _ServerHarness(ws, host="0.0.0.0") as harness:
            # Host header is still validated against the loopback allowlist, so
            # the request is served only with a loopback Host; the point is the
            # PAGE must not contain the token.
            status, body = _request(harness.port, "/")
            assert status == 200, body
            assert harness.token not in body
            assert "__NEXUSOS_TOKEN__" not in body
    except OSError:
        # Some CI sandboxes refuse to bind 0.0.0.0; the behavior is unit-tested
        # via the handler attribute below.
        pytest.skip("cannot bind 0.0.0.0 in this environment")


def test_f10_loopback_bind_embeds_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Loopback bind still embeds the token so the bundled UI keeps working."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with _ServerHarness(ws, host="127.0.0.1") as harness:
        status, body = _request(harness.port, "/")
        assert status == 200
        assert harness.token in body


def test_f10_handler_attr_loopback_vs_non_loopback(tmp_path: Path) -> None:
    """The inject_ui_token handler attribute mirrors the bind host."""
    from nexusos.services.serve_service import create_server

    ws = tmp_path / "ws"
    ws.mkdir()

    loopback = create_server(ws, host="127.0.0.1", port=0)
    try:
        handler_cls = cast("type[object]", loopback.RequestHandlerClass)
        assert handler_cls.inject_ui_token is True
    finally:
        loopback.server_close()

    non_loopback = create_server(ws, host="0.0.0.0", port=0)
    try:
        handler_cls = cast("type[object]", non_loopback.RequestHandlerClass)
        assert handler_cls.inject_ui_token is False
    finally:
        non_loopback.server_close()


# ---------------------------------------------------------------------------
# F-11 — source immutability across CLI, HTTP, and MCP stdio retrieval
# ---------------------------------------------------------------------------


def test_f11_cli_retrieval_does_not_mutate_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI retrieval (status/search/read/browse) leaves source bytes untouched."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    before = _source_snapshot(ws)

    from nexusos.services.navigation_service import browse_workspace, read_document
    from nexusos.services.search_service import search_workspace
    from nexusos.services.status_service import get_status

    get_status(ws)
    search_workspace(ws, "alpha", limit=5)
    read_document(ws, "wiki/alpha.md")
    browse_workspace(ws, limit=10)

    after = _source_snapshot(ws)
    assert after == before


def test_f11_http_retrieval_does_not_mutate_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kernel-data HTTP retrieval (/api/documents) leaves source bytes untouched."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    before = _source_snapshot(ws)

    with _ServerHarness(ws, host="127.0.0.1") as harness:
        status, body = _request(
            harness.port,
            "/api/documents",
            headers={"X-NexusOS-Token": harness.token},
        )
        assert status == 200, body
        assert "alpha.md" in body
        status2, body2 = _request(
            harness.port,
            "/api/documents/wiki/alpha.md",
            headers={"X-NexusOS-Token": harness.token},
        )
        assert status2 == 200, body2
        assert "Secret material" in body2

    after = _source_snapshot(ws)
    assert after == before


def test_f11_mcp_stdio_retrieval_does_not_mutate_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP stdio read/search tools leave source bytes untouched."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    before = _source_snapshot(ws)

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("NEXUSOS_DENY_PATHS", None)

    async def _run() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "nexusos.mcp", "--workspace", str(ws)],
            env=env,
            cwd=str(ws),
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {"search", "read", "status"}.issubset(names)
            await session.call_tool("search", {"term": "alpha"})
            await session.call_tool("read", {"item": "wiki/alpha.md"})
            await session.call_tool("status", {})

    asyncio.run(_run())
    after = _source_snapshot(ws)
    assert after == before


# ---------------------------------------------------------------------------
# F-12 — index database file permissions
# ---------------------------------------------------------------------------


def test_f12_index_database_is_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    db = ws / ".nexusos" / "index.sqlite3"
    assert db.is_file()
    assert _mode(db) == 0o600


# ---------------------------------------------------------------------------
# F-13 — search term length bound (service + MCP schema)
# ---------------------------------------------------------------------------


def test_f13_search_service_rejects_oversized_term(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    from nexusos.core.errors import IndexingError
    from nexusos.services.search_service import search_workspace

    with pytest.raises(IndexingError):
        search_workspace(ws, "x" * (MAX_SEARCH_TERM_LENGTH + 1))
    # Boundary value still works (no workspace-level limit error for a valid
    # term; the workspace is indexed, so a real search runs).
    result = search_workspace(ws, "x" * MAX_SEARCH_TERM_LENGTH, limit=1)
    assert result.total >= 0


def test_f13_mcp_schema_rejects_oversized_term() -> None:
    from pydantic import ValidationError

    from nexusos.mcp.server import SearchArgs

    with pytest.raises(ValidationError):
        SearchArgs(term="x" * (MAX_SEARCH_TERM_LENGTH + 1))
    assert SearchArgs(term="ok").term == "ok"


# ---------------------------------------------------------------------------
# HTTP path traversal
# ---------------------------------------------------------------------------


def test_http_document_path_traversal_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Traversal attempts on /api/documents/... must not escape the index."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with _ServerHarness(ws, host="127.0.0.1") as harness:
        for evil in (
            "/api/documents/../../etc/passwd",
            "/api/documents/..%2f..%2fetc%2fpasswd",
            "/api/documents/%2e%2e/%2e%2e/etc/passwd",
            "/api/documents/....//....//etc/passwd",
        ):
            status, body = _request(
                harness.port,
                evil,
                headers={"X-NexusOS-Token": harness.token},
            )
            assert status in (200, 404), f"{evil}: {status} {body}"
            # A 200 means the document lookup simply found nothing (no such
            # relative path); it must never return an outside file's content.
            if status == 200:
                assert "root:" not in body


def test_http_ui_asset_traversal_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Traversal attempts on /ui/... must be forbidden."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with _ServerHarness(ws, host="127.0.0.1") as harness:
        for evil in (
            "/ui/../../etc/passwd",
            "/ui/..%2f..%2fetc%2fpasswd",
            "/ui/%2e%2e/%2e%2e/etc/passwd",
        ):
            status, body = _request(harness.port, evil)
            assert status in (403, 404), f"{evil}: {status} {body}"

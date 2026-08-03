"""Integration tests for the vault lint + serve transports via the real CLI.

Exercises ``nexusos lint --workspace`` end-to-end (clean vault exits 0,
broken vault exits 1, JSON output) and ``nexusos serve --transport stdio``
(the card's smoke entrypoint) plus the Streamable HTTP transport.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import pytest

from nexusos.workspace.init import init_workspace

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
if os.name == "nt":
    NEXUSOS_BIN = REPO_ROOT / ".venv" / "Scripts" / "nexusos.exe"
else:
    NEXUSOS_BIN = REPO_ROOT / ".venv" / "bin" / "nexusos"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("NEXUSOS_DENY_PATHS", None)
    return env


def _run_cli(ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(NEXUSOS_BIN), *args, "--workspace", str(ws)],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(ws),
        timeout=60,
    )


def _make_workspace(tmp_path: Path, *, broken: bool = False) -> Path:
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / "alpha.md").write_text("# Alpha\n\nBody text.\n", encoding="utf-8")
    if broken:
        (ws / "wiki" / "beta.md").write_text("# Beta\n\nSee [[missing-page]].\n", encoding="utf-8")
    else:
        (ws / "wiki" / "beta.md").write_text("# Beta\n\nSee [[alpha]].\n", encoding="utf-8")
    return ws


def _read_until(
    proc: subprocess.Popen[str],
    needle: str,
    *,
    timeout: float = 60.0,
) -> str:
    """Read ``proc`` stdout until ``needle`` appears, EOF, or timeout.

    Uses a daemon reader thread feeding a queue so the wait is strictly
    bounded: a silent-but-alive child must not block ``readline()`` (or the
    assert message's ``read()``) forever past the deadline. Returns all
    output read so far. The default is generous (60s) because a cold
    subprocess on a shared CI runner (macOS in particular) can take tens
    of seconds to import and print its first line.
    """
    lines: queue.Queue[str | None] = queue.Queue()

    def _drain() -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    output = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and needle not in output:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            break
        if line is None:
            break
        output += line
    return output


# -- lint ---------------------------------------------------------------------


def test_lint_clean_vault_exit_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    from nexusos.services.index_service import index_workspace

    ws = _make_workspace(tmp_path, broken=False)
    run = index_workspace(ws, full=True)
    assert run.success
    proc = _run_cli(ws, "lint")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NexusOS vault lint" in proc.stdout
    assert "Vault lint clean." in proc.stdout


def test_lint_broken_vault_exit_one(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, broken=True)
    proc = _run_cli(ws, "lint")
    assert proc.returncode == 1
    assert "broken-links" in proc.stdout
    assert "missing-page" in proc.stdout


def test_lint_json_output(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, broken=True)
    proc = _run_cli(ws, "lint", "--json")
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["workspace"] == str(ws)
    assert payload["has_findings"] is True
    assert any(c["name"] == "broken-links" for c in payload["checks"])


def test_lint_after_index_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = _make_workspace(tmp_path, broken=False)
    index_proc = _run_cli(ws, "index")
    assert index_proc.returncode == 0, index_proc.stderr
    lint_proc = _run_cli(ws, "lint")
    assert lint_proc.returncode == 0, lint_proc.stdout
    assert "stale-index" in lint_proc.stdout
    assert "index is fresh" in lint_proc.stdout


def test_lint_unknown_workspace_exit_error(tmp_path: Path) -> None:
    proc = _run_cli(tmp_path, "lint")
    assert proc.returncode != 0


# -- serve transports ----------------------------------------------------------


def _server_params(ws: Path, *extra: str):
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=str(NEXUSOS_BIN),
        args=["serve", "--transport", "stdio", "--workspace", str(ws), *extra],
        env=_env(),
        cwd=str(ws),
    )


def test_serve_stdio_handshake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    from nexusos.services.index_service import index_workspace

    ws = _make_workspace(tmp_path, broken=False)
    run = index_workspace(ws, full=True)
    assert run.success

    async def _run() -> tuple[str, list[str]]:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        params = _server_params(ws)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            info = await session.initialize()
            tools = await session.list_tools()
            return info.server_info.name, [t.name for t in tools.tools]

    name, tools = asyncio.run(_run())
    assert name == "nexusos"
    assert tools == ["status", "search", "browse", "read", "recent", "links", "context", "index"]


def test_serve_http_transport_starts_and_serves(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, broken=False)
    port = 19876
    proc = subprocess.Popen(
        [
            str(NEXUSOS_BIN),
            "serve",
            "--transport",
            "http",
            "--workspace",
            str(ws),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_env(),
        cwd=str(ws),
    )
    try:
        import re
        import urllib.request

        # The CLI prints the per-process API token on startup; /api/* reads
        # require it (F-02). Read the startup output until the token appears.
        # _read_until is strictly bounded: a silent-but-alive child must not
        # block the read (or the assert message) forever past the deadline.
        output = _read_until(proc, "API token:")
        match = re.search(r"API token: (\S+)", output)
        assert match is not None, f"server did not print API token; output:\n{output}"
        token = match.group(1)

        url = f"http://127.0.0.1:{port}/api/status"
        status = None
        req = urllib.request.Request(url, headers={"X-NexusOS-Token": token})
        for _ in range(40):
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(req, timeout=1) as resp:
                    status = resp.status
                    break
            except Exception:
                time.sleep(0.25)
        assert status == 200, proc.stdout.read()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_serve_unknown_transport_rejected(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, broken=False)
    proc = _run_cli(ws, "serve", "--transport", "bogus")
    assert proc.returncode == 2
    assert "unknown transport" in proc.stderr


def test_serve_non_loopback_host_warns(tmp_path: Path) -> None:
    """Binding to a non-loopback host must print an explicit warning (F-08)."""
    ws = _make_workspace(tmp_path, broken=False)
    port = 19877
    proc = subprocess.Popen(
        [
            str(NEXUSOS_BIN),
            "serve",
            "--transport",
            "http",
            "--workspace",
            str(ws),
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_env(),
        cwd=str(ws),
    )
    try:
        # The warning is printed at startup; read until it (or timeout)
        # appears. _read_until is strictly bounded so a silent child cannot
        # block the read forever.
        output = _read_until(proc, "Warning")
        assert "Warning" in output, f"no non-loopback warning; output:\n{output}"
        assert "0.0.0.0" in output
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

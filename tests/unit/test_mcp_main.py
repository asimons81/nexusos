"""Unit tests for the ``python -m nexusos.mcp`` entrypoint.

The entrypoint is security-relevant: it enforces the F-08 non-loopback bind
refusal for the unauthenticated Streamable HTTP surface and the disabled /
unsupported-transport error exits that keep the stdio protocol channel clean.
Integration tests spawn the real subprocess (which coverage does not trace),
so these unit tests exercise ``_resolve_workspace`` and ``main`` directly
with a faked server to lift coverage on the entrypoint itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import nexusos.mcp.__main__ as mcp_main
from nexusos.core.models import NexusOSConfig


class _FakeServer:
    """Minimal stand-in for the real MCP server (records ``run`` calls)."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    def run(self, **kwargs: Any) -> None:
        self.runs.append(kwargs)


def _patch_server(monkeypatch: pytest.MonkeyPatch, config: NexusOSConfig) -> _FakeServer:
    """Replace ``build_server`` with a fake; return the fake server."""
    fake = _FakeServer()
    monkeypatch.setattr(mcp_main, "build_server", lambda *args, **kwargs: fake)
    monkeypatch.setattr(mcp_main, "load_config_effective", lambda root: config)
    return fake


def test_resolve_workspace_explicit(tmp_path: Path) -> None:
    target = tmp_path / "ws"
    target.mkdir()
    assert mcp_main._resolve_workspace(str(target)) == target.resolve()


def test_resolve_workspace_detects_nearest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_main, "find_nearest_workspace_root", lambda cwd: Path("/srv/ws"))
    assert mcp_main._resolve_workspace(None) == Path("/srv/ws")


def test_resolve_workspace_missing_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_main, "find_nearest_workspace_root", lambda cwd: None)
    with pytest.raises(SystemExit) as exc:
        mcp_main._resolve_workspace(None)
    assert exc.value.code == 2


def test_main_disabled_exits_three(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = NexusOSConfig(mcp_enabled=False)
    _patch_server(monkeypatch, config)
    with pytest.raises(SystemExit) as exc:
        mcp_main.main(["--workspace", str(tmp_path)])
    assert exc.value.code == 3


def test_main_unsupported_transport_exits_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = NexusOSConfig(mcp_transport="http")
    _patch_server(monkeypatch, config)
    with pytest.raises(SystemExit) as exc:
        mcp_main.main(["--workspace", str(tmp_path)])
    assert exc.value.code == 3


def test_main_streamable_http_non_loopback_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUSOS_ALLOW_NON_LOOPBACK", raising=False)
    config = NexusOSConfig(mcp_transport="streamable-http", server_host="0.0.0.0")
    _patch_server(monkeypatch, config)
    with pytest.raises(SystemExit) as exc:
        mcp_main.main(["--workspace", str(tmp_path)])
    assert exc.value.code == 2


def test_main_streamable_http_loopback_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUSOS_ALLOW_NON_LOOPBACK", raising=False)
    config = NexusOSConfig(mcp_transport="streamable-http", server_host="127.0.0.1")
    fake = _patch_server(monkeypatch, config)
    mcp_main.main(["--workspace", str(tmp_path)])
    assert fake.runs == [{"transport": "streamable-http", "host": "127.0.0.1", "port": 8765}]


def test_main_stdio_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = NexusOSConfig(mcp_transport="stdio")
    fake = _patch_server(monkeypatch, config)
    mcp_main.main(["--workspace", str(tmp_path)])
    assert fake.runs == [{"transport": "stdio"}]

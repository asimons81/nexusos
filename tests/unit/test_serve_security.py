"""Security regression tests for the kernel-data HTTP server (F-02).

Covers the Host-header / DNS-rebinding exposure fixed for finding F-02 from
the security probe: the serve handler must reject non-loopback Host headers,
require a per-server API token for /api/* reads, reject foreign Origin
headers, and keep the loopback-only default with a non-loopback warning.
"""

from __future__ import annotations

import http.client
import threading
from typing import TYPE_CHECKING

import pytest

from nexusos.services.serve_service import (
    _host_without_port,
    _origin_is_loopback,
    create_server,
    is_allowed_host,
    is_loopback_host,
)
from nexusos.workspace.init import init_workspace

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# L2 — host allowlist helpers
# ---------------------------------------------------------------------------


def test_host_without_port_strips_v4_port() -> None:
    assert _host_without_port("127.0.0.1:8899") == "127.0.0.1"
    assert _host_without_port("localhost:8899") == "localhost"
    assert _host_without_port("127.0.0.1") == "127.0.0.1"


def test_host_without_port_strips_ipv6_brackets_and_port() -> None:
    assert _host_without_port("[::1]:8899") == "::1"
    assert _host_without_port("[::1]") == "::1"
    assert _host_without_port("::1") == "::1"


def test_host_without_port_keeps_hostname_with_non_numeric_suffix() -> None:
    # A trailing colon in a malformed header must not turn an evil host into
    # a loopback one (Host: 127.0.0.1.evil.com:8899 stays evil).
    assert _host_without_port("127.0.0.1.evil.com:8899") == "127.0.0.1.evil.com"
    assert _host_without_port("evil.example.com") == "evil.example.com"


def test_is_allowed_host_accepts_loopback_forms() -> None:
    for host in (
        "127.0.0.1",
        "127.0.0.1:8899",
        "localhost",
        "localhost:8899",
        "[::1]",
        "[::1]:8899",
        "::1",
        "LOCALHOST",
    ):
        assert is_allowed_host(host), f"{host!r} should be allowed"


def test_is_allowed_host_rejects_foreign_and_missing() -> None:
    for host in (
        "evil.example.com",
        "evil.example.com:8899",
        "127.0.0.1.evil.com",
        "127.0.0.1.evil.com:8899",
        "10.0.0.1",
        "192.168.1.1",
        "",
    ):
        assert not is_allowed_host(host), f"{host!r} should be rejected"


def test_is_allowed_host_rejects_malformed_ipv6_brackets() -> None:
    """Regression (review): malformed bracketed hosts must not normalize to ::1."""
    for host in (
        "[::1",
        "[::1]evil",
        "[::1]:9999evil",
        "[::1]:evil",
        "[127.0.0.1",
        "[localhost]",
    ):
        assert not is_allowed_host(host), f"{host!r} should be rejected"
    # The well-formed forms remain accepted.
    for host in ("[::1]", "[::1]:8899"):
        assert is_allowed_host(host), f"{host!r} should be allowed"


def test_is_loopback_host_bind_forms() -> None:
    for host in ("127.0.0.1", "localhost", "::1", "[::1]"):
        assert is_loopback_host(host), f"{host!r} should count as loopback"
    for host in ("0.0.0.0", "::", "10.0.0.1", "192.168.1.1", ""):
        assert not is_loopback_host(host), f"{host!r} should warn"


def test_origin_is_loopback() -> None:
    for origin in (
        "http://127.0.0.1:8899",
        "http://localhost:8899",
        "http://[::1]:8899",
        "https://127.0.0.1:8899",
    ):
        assert _origin_is_loopback(origin), f"{origin!r} should be loopback"
    for origin in (
        "http://evil.example.com",
        "https://evil.example.com",
        "null",
        "",
        "file:///tmp/x",
    ):
        assert not _origin_is_loopback(origin), f"{origin!r} should be foreign"


# ---------------------------------------------------------------------------
# L4 — real HTTP against a running server
# ---------------------------------------------------------------------------


class ServeHarness:
    """Start a serve server on an ephemeral port for the duration of a test."""

    def __init__(self, workspace: Path) -> None:
        self.server = create_server(workspace, host="127.0.0.1", port=0)
        self.token = self.server.nexusos_token
        self._thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()
        _host, self.port = self.server.server_address[:2]

    def __enter__(self) -> ServeHarness:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)


def _request(
    port: int,
    path: str,
    *,
    host: str | None = None,
    headers: dict[str, str] | None = None,
    extra_hosts: list[str] | None = None,
) -> tuple[int, str]:
    """GET a path with an explicit Host header (default loopback) + headers.

    ``extra_hosts`` sends additional Host headers to exercise the
    duplicate-Host rejection (RFC 7230 §5.4).
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
        for extra in extra_hosts or []:
            conn.putheader("Host", extra)
        for key, value in (headers or {}).items():
            conn.putheader(key, value)
        conn.endheaders()
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


def _make_indexed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / "secret.md").write_text(
        "# Secret\n\npassword=super-secret-value\n", encoding="utf-8"
    )
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws, full=True)
    assert run.success
    return ws


def test_dns_rebinding_host_header_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for F-02: a foreign Host header must be rejected outright."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        # The DNS-rebinding attack: attacker.com resolves to 127.0.0.1, so the
        # browser connects to us but sends Host: attacker.com.
        status, body = _request(
            harness.port,
            "/api/documents",
            host="evil.example.com",
            headers={"X-NexusOS-Token": harness.token},
        )
        assert status == 403, body
        assert "forbidden" in body.lower() or "invalid" in body.lower()

        # Even the UI page and healthz are unreachable with a foreign Host.
        status2, _ = _request(harness.port, "/", host="evil.example.com")
        assert status2 == 403

        # A valid loopback Host still serves.
        status3, _ = _request(harness.port, "/healthz", host=f"127.0.0.1:{harness.port}")
        assert status3 == 200


def test_api_documents_requires_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The full indexed document text must not be readable without the token."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        status, body = _request(harness.port, "/api/documents")
        assert status == 403, body

        # With the token, the secret document is served (legit local access).
        status2, body2 = _request(
            harness.port, "/api/documents", headers={"X-NexusOS-Token": harness.token}
        )
        assert status2 == 200
        assert "secret.md" in body2

        status3, body3 = _request(
            harness.port,
            "/api/documents/wiki/secret.md",
            headers={"X-NexusOS-Token": harness.token},
        )
        assert status3 == 200
        assert "super-secret-value" in body3


def test_api_status_requires_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        status, _ = _request(harness.port, "/api/status")
        assert status == 403
        status2, body2 = _request(
            harness.port, "/api/status", headers={"X-NexusOS-Token": harness.token}
        )
        assert status2 == 200
        assert '"status"' in body2


def test_api_rejects_foreign_origin_even_with_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cross-origin browser request must fail even if it somehow has the token."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        status, body = _request(
            harness.port,
            "/api/documents",
            headers={"X-NexusOS-Token": harness.token, "Origin": "http://evil.example.com"},
        )
        assert status == 403, body


def test_loopback_origin_with_token_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bundled UI's same-origin fetches (Origin: http://127.0.0.1:PORT) work."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        status, _ = _request(
            harness.port,
            "/api/documents",
            headers={
                "X-NexusOS-Token": harness.token,
                "Origin": f"http://127.0.0.1:{harness.port}",
            },
        )
        assert status == 200


def test_root_page_injects_api_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The served UI page must contain the real token so its JS can call /api/*."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        status, body = _request(harness.port, "/")
        assert status == 200
        assert harness.token in body
        assert "__NEXUSOS_TOKEN__" not in body


def test_healthz_open_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Healthz stays open (no index data); loopback Host is enough."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        status, _ = _request(harness.port, "/healthz")
        assert status == 200


def test_duplicate_host_headers_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (review): multiple Host headers are rejected (RFC 7230 §5.4)."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        status, body = _request(
            harness.port,
            "/healthz",
            extra_hosts=["evil.example.com"],
            headers={"X-NexusOS-Token": harness.token},
        )
        assert status == 400, body
        assert "Host" in body


def test_malformed_ipv6_bracket_host_rejected_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (review): malformed bracketed hosts are rejected over the wire."""
    ws = _make_indexed_workspace(tmp_path, monkeypatch)
    with ServeHarness(ws) as harness:
        for bad_host in ("[::1", "[::1]evil", "[::1]:9999evil"):
            status, body = _request(
                harness.port,
                "/api/documents",
                host=bad_host,
                headers={"X-NexusOS-Token": harness.token},
            )
            assert status == 403, f"{bad_host!r} should be rejected: {body}"

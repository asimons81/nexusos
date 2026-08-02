"""Local HTTP server exposing NexusOS kernel data (`nexusos serve`).

Developer tooling: starts a read-only loopback HTTP server that exposes the
kernel's derived data (status, meta, counts, documents, index runs) as JSON,
plus any packaged UI assets from ``src/nexusos/ui/``. It is intentionally
read-only: it never creates or mutates the index database, and it never
touches source documents. The CLI command shuts the server down cleanly on
SIGINT/SIGTERM.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from nexusos import __version__
from nexusos.indexing.kernel import IndexKernel
from nexusos.services.status_service import get_status

#: Package UI assets directory (bundled HTML/JS/CSS), if present.
UI_DIR = Path(__file__).resolve().parent.parent / "ui"

#: Read-only kernel meta keys exposed at /api/meta.
_META_KEYS = (
    "index_schema_version",
    "workspace_id",
    "application_version",
    "last_successful_index_at",
    "last_index_run_id",
    "config_fingerprint",
)


def _index_db_path(workspace_root: Path) -> Path:
    return workspace_root / ".nexusos" / "index.sqlite3"


def _serialize(obj: Any) -> Any:
    """JSON-encode pydantic objects and paths defensively."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, Path):
        return str(obj)
    return obj


class _NexusOSHandler(BaseHTTPRequestHandler):
    """HTTP handler exposing the workspace's kernel data (read-only)."""

    server_version = f"NexusOSServe/{__version__}"
    workspace_root: Path
    _kernel: IndexKernel | None = None

    # -- helpers -------------------------------------------------------------

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=_serialize, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(
        self,
        body: str,
        status: int = 200,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json({"error": "not found"}, status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _with_kernel(self) -> dict[str, Any] | None:
        """Open the kernel read-only; return an error payload when unavailable.

        Returns None when the kernel opened successfully (the caller is
        responsible for closing it). Otherwise returns a JSON-serializable
        error payload to serve with a 404.
        """
        ws = self.workspace_root
        if not _index_db_path(ws).is_file():
            return {
                "error": "no index database",
                "hint": "run `nexusos index --workspace <path>` first",
            }
        kernel = IndexKernel(ws)
        try:
            kernel.open(create_parent=False)
        except Exception as exc:  # serve errors are user-facing
            return {"error": "cannot open index", "detail": str(exc)}
        self._kernel = kernel
        return None

    def _close_kernel(self) -> None:
        if self._kernel is not None:
            try:
                self._kernel.close()
            finally:
                self._kernel = None

    # -- routing -------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/healthz":
            self._send_json({"ok": True, "version": __version__})
            return
        if path == "/":
            self._serve_root_page()
            return
        if path == "/api/status":
            self._send_json(get_status(self.workspace_root))
            return
        if path == "/api/meta":
            self._serve_meta()
            return
        if path == "/api/counts":
            self._serve_counts()
            return
        if path == "/api/documents":
            self._serve_documents()
            return
        if path.startswith("/api/documents/"):
            self._serve_document(path[len("/api/documents/") :])
            return
        if path == "/api/runs":
            self._serve_runs()
            return
        if path.startswith("/ui/"):
            self._serve_ui_asset(path[len("/ui/") :])
            return

        self._send_json({"error": "not found", "path": path}, status=404)

    # -- endpoint implementations --------------------------------------------

    def _serve_root_page(self) -> None:
        index_html = UI_DIR / "index.html"
        if index_html.is_file():
            self._send_file(index_html)
        else:
            self._send_text(
                "NexusOS kernel data server\n"
                "Endpoints: /healthz /api/status /api/meta /api/counts "
                "/api/documents /api/runs\n",
                content_type="text/plain; charset=utf-8",
            )

    def _serve_meta(self) -> None:
        err = self._with_kernel()
        if err is not None:
            self._send_json(err, status=404)
            return
        kernel = self._kernel
        assert kernel is not None
        try:
            meta = {key: kernel.get_meta(key) for key in _META_KEYS}
            self._send_json(meta)
        finally:
            self._close_kernel()

    def _serve_counts(self) -> None:
        err = self._with_kernel()
        if err is not None:
            self._send_json(err, status=404)
            return
        kernel = self._kernel
        assert kernel is not None
        try:
            self._send_json(kernel.counts())
        finally:
            self._close_kernel()

    def _serve_documents(self) -> None:
        err = self._with_kernel()
        if err is not None:
            self._send_json(err, status=404)
            return
        kernel = self._kernel
        assert kernel is not None
        try:
            # status_service uses the same private accessor for read-only queries.
            self._send_json(kernel._db.list_documents())
        finally:
            self._close_kernel()

    def _serve_document(self, relative_path: str) -> None:
        err = self._with_kernel()
        if err is not None:
            self._send_json(err, status=404)
            return
        kernel = self._kernel
        assert kernel is not None
        try:
            doc = kernel.get_document(relative_path)
            if doc is None:
                self._send_json({"error": "document not found", "path": relative_path}, status=404)
                return
            self._send_json(doc)
        finally:
            self._close_kernel()

    def _serve_runs(self) -> None:
        err = self._with_kernel()
        if err is not None:
            self._send_json(err, status=404)
            return
        kernel = self._kernel
        assert kernel is not None
        try:
            self._send_json(kernel.get_last_run())
        finally:
            self._close_kernel()

    def _serve_ui_asset(self, rel_path: str) -> None:
        if not UI_DIR.is_dir():
            self._send_json({"error": "ui assets not bundled"}, status=404)
            return
        candidate = (UI_DIR / rel_path).resolve()
        try:
            candidate.relative_to(UI_DIR.resolve())
        except ValueError:
            self._send_json({"error": "forbidden"}, status=403)
            return
        if not candidate.is_file():
            self._send_json({"error": "not found"}, status=404)
            return
        self._send_file(candidate)

    # -- http.server noise suppression ---------------------------------------

    def log_message(self, format: str, *args: object) -> None:
        # Keep the dev server quiet; the CLI prints a shutdown message itself.
        pass


def create_server(
    workspace_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Create (but do not start) a kernel-data HTTP server for a workspace.

    Returns a bound :class:`ThreadingHTTPServer`; call ``serve_forever`` to
    run it. The workspace must already be initialized (a ``nexusos.toml`` and
    ``.nexusos/workspace.json``), but it does not need to be indexed — data
    endpoints report a clear 404 until ``nexusos index`` has run.
    """
    root = Path(workspace_root).resolve(strict=False)
    # Bind the workspace root as a class attribute on a per-server handler
    # subclass (partial() cannot inject extra constructor kwargs into
    # BaseHTTPRequestHandler).
    handler = type("_NexusOSHandler", (_NexusOSHandler,), {"workspace_root": root})
    server = ThreadingHTTPServer((host, port), handler)
    return server

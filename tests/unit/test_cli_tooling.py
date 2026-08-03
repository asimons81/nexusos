"""Smoke tests for the dev tooling commands: lint, serve, demo.

Covers the acceptance criteria for task t_5eab3ef4:
- commands are registered and documented in ``--help``
- can be invoked without crashing
- lint returns exit code 0 / non-zero based on static-check findings
- serve exposes kernel data over HTTP and shuts down cleanly on SIGINT
- demo runs a scripted walkthrough and prints usage examples
- existing test suite still passes (checked by the full suite run)

Test plan (Gate 1):
- L1 source presence: modules import, commands registered in --help
- L2 value correctness: lint report shape and exit codes, serve endpoint
  responses and read-only guarantee, demo walkthrough artifacts
- L3 cross-reference: help text documents flags; README/CHANGELOG updated
- L4 runtime behavior: real ``nexusos serve`` subprocess SIGINT shutdown,
  real ``nexusos lint`` and ``nexusos demo`` invocations
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexusos.cli.main import app
from nexusos.services import demo_service, lint_service, serve_service
from nexusos.workspace.init import init_workspace

runner = CliRunner()

#: Repository root (tests/unit/test_cli_tooling.py → repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Files owned by this change that the clean-repo copy overlays on top of the
#: git baseline, so the lint tests exercise a deterministic tree instead of
#: whatever unrelated work-in-progress happens to be in the working tree.
#: main.py is intentionally NOT overlaid: the working-tree version imports
#: sibling in-progress modules, so the copy keeps the baseline CLI.
_OVERLAY_FILES = (
    "pyproject.toml",
    "src/nexusos/core/config.py",
    "src/nexusos/core/errors.py",
    "src/nexusos/core/limits.py",
    "src/nexusos/core/models.py",
    "src/nexusos/core/path_safety.py",
    "src/nexusos/indexing/database.py",
    "src/nexusos/indexing/indexer.py",
    "src/nexusos/indexing/kernel.py",
    "src/nexusos/indexing/migrations.py",
    "src/nexusos/indexing/models.py",
    "src/nexusos/indexing/schema.py",
    "src/nexusos/mcp/__main__.py",
    "src/nexusos/mcp/server.py",
    "src/nexusos/services/doctor.py",
    "src/nexusos/services/lint_service.py",
    "src/nexusos/services/navigation_service.py",
    "src/nexusos/services/search_service.py",
    "src/nexusos/services/serve_service.py",
    "src/nexusos/services/status_service.py",
    "src/nexusos/services/demo_service.py",
    "src/nexusos/workspace/init.py",
    "src/nexusos/ui/index.html",
)


@pytest.fixture(scope="session")
def clean_repo_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A pristine copy of the repo baseline plus this change's files.

    The lint tests need a clean tree: the shared working tree may contain
    unrelated concurrent work-in-progress, so `nexusos lint` against it is
    not deterministic. This fixture materializes exactly the state this
    change produces (baseline + overlay files) and links the repo's venv so
    the tools resolve.
    """
    target = tmp_path_factory.mktemp("clean_repo")
    proc = subprocess.run(
        ["git", "archive", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    subprocess.run(["tar", "-x", "-C", str(target)], input=proc.stdout, check=True)
    for rel in _OVERLAY_FILES:
        src = REPO_ROOT / rel
        if src.is_file():
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    (target / ".venv").symlink_to(REPO_ROOT / ".venv", target_is_directory=True)
    return target


def _http_get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    """GET a URL and return (status, body)."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, body


class ServeHarness:
    """Start a serve server on an ephemeral port for the duration of a test.

    Usable as a context manager: ``with serve_harness(ws) as h:``.
    """

    def __init__(self, workspace: Path, **kwargs: object) -> None:
        self.server = serve_service.create_server(workspace, host="127.0.0.1", port=0, **kwargs)
        self.token = self.server.nexusos_token
        self._thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def __enter__(self) -> ServeHarness:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)

    def get(self, path: str) -> tuple[int, str]:
        """GET a path on this server with the API token attached."""
        return _http_get(f"{self.base_url}{path}", headers={"X-NexusOS-Token": self.token})


def serve_harness(workspace: Path) -> ServeHarness:
    """Start a serve server for ``workspace`` on an ephemeral port."""
    return ServeHarness(workspace)


def _make_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "ws") -> Path:
    """Create an initialized NexusOS workspace with a few sample documents."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / name
    init_workspace(ws, template="starter")
    (ws / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)
    (ws / "wiki" / "concepts" / "agents.md").write_text(
        "---\ntitle: AI Agents\nstatus: active\n---\n"
        "# AI Agents\n\nAgents use [[memory]] to persist knowledge.\n",
        encoding="utf-8",
    )
    (ws / "wiki" / "concepts" / "memory.md").write_text(
        "---\ntitle: Memory\n---\n# Memory\n\nMemory is indexed from [[agents]].\n",
        encoding="utf-8",
    )
    return ws


# ---------------------------------------------------------------------------
# L1 + L3 — registration and help documentation
# ---------------------------------------------------------------------------


def test_help_lists_lint_serve_demo() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("lint", "serve", "demo"):
        assert cmd in result.output


def test_lint_help_documents_flags() -> None:
    result = runner.invoke(app, ["lint", "--help"])
    assert result.exit_code == 0
    assert "--tool" in result.output
    assert "--json" in result.output


def test_serve_help_documents_flags() -> None:
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--host" in result.output
    assert "--workspace" in result.output


def test_demo_help_documents_flags() -> None:
    result = runner.invoke(app, ["demo", "--help"])
    assert result.exit_code == 0
    assert "--path" in result.output
    assert "--remove" in result.output


# ---------------------------------------------------------------------------
# L2 — lint service value correctness
# ---------------------------------------------------------------------------


def test_find_repo_root_resolves_to_project() -> None:
    root = lint_service.find_repo_root()
    assert root is not None
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "nexusos").is_dir()


def test_lint_service_returns_report_with_tool_checks(clean_repo_copy: Path) -> None:
    report = lint_service.run_lint(repo_root=clean_repo_copy)
    tools = {check.tool for check in report.checks}
    assert tools == {"ruff", "format", "mypy"}
    assert report.passed == 3
    assert report.failed == 0
    assert report.errors == 0
    assert report.has_findings is False


def test_lint_service_selects_single_tool(clean_repo_copy: Path) -> None:
    report = lint_service.run_lint(repo_root=clean_repo_copy, tool="mypy")
    assert [check.tool for check in report.checks] == ["mypy"]
    assert report.passed == 1


def test_lint_service_missing_tool_is_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = lint_service.find_repo_root()
    assert root is not None

    real_find = lint_service._find_tool

    def fake_find(name: str, repo_root: Path) -> str | None:
        if name == "mypy":
            return None
        return real_find(name, repo_root)

    monkeypatch.setattr(lint_service, "_find_tool", fake_find)
    report = lint_service.run_lint(repo_root=root)
    mypy_check = next(c for c in report.checks if c.tool == "mypy")
    assert mypy_check.status == "error"
    assert report.has_findings is True


# ---------------------------------------------------------------------------
# L2 — serve endpoints and read-only guarantee
# ---------------------------------------------------------------------------


def test_serve_healthz_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_workspace(tmp_path, monkeypatch)
    with serve_harness(ws) as harness:
        status, body = _http_get(f"{harness.base_url}/healthz")
        assert status == 200
        assert json.loads(body)["ok"] is True


def test_serve_status_uninitialized_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _make_workspace(tmp_path, monkeypatch)
    with serve_harness(ws) as harness:
        status, body = harness.get("/api/status")
        assert status == 200
        assert json.loads(body)["status"] == "uninitialized"
        # data endpoints must not create the database
        status2, _ = harness.get("/api/documents")
        assert status2 == 404
        assert not (ws / ".nexusos" / "index.sqlite3").exists()
        assert not (ws / ".nexusos" / "index.lock").exists()


def test_serve_documents_and_root_page_after_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _make_workspace(tmp_path, monkeypatch)
    from nexusos.services.index_service import index_workspace

    run = index_workspace(ws)
    assert run.success
    with serve_harness(ws) as harness:
        status, body = harness.get("/api/status")
        assert status == 200
        assert json.loads(body)["document_count"] >= 2
        status2, body2 = harness.get("/api/documents")
        assert status2 == 200
        docs = json.loads(body2)
        assert isinstance(docs, list)
        assert len(docs) >= 2
        assert docs[0]["normalized_path"]
        status3, body3 = _http_get(f"{harness.base_url}/")
        assert status3 == 200
        assert "text/html" in body3.lower() or "<html" in body3.lower()
        status4, _ = _http_get(f"{harness.base_url}/nope")
        assert status4 == 404


def test_serve_document_lookup_and_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_workspace(tmp_path, monkeypatch)
    from nexusos.services.index_service import index_workspace

    index_workspace(ws)
    with serve_harness(ws) as harness:
        status, body = harness.get("/api/counts")
        assert status == 200
        counts = json.loads(body)
        # Starter template ships root README.md + SCHEMA.md; the **/*.md fix
        # now discovers and indexes them alongside the two wiki docs
        # (previously root files were silently skipped).
        assert counts["document_count"] == 4
        status2, body2 = harness.get("/api/documents/wiki/concepts/agents.md")
        assert status2 == 200
        doc = json.loads(body2)
        assert doc["title"] == "AI Agents"
        status3, _ = harness.get("/api/documents/does/not/exist.md")
        assert status3 == 404


# ---------------------------------------------------------------------------
# L2 — demo service value correctness
# ---------------------------------------------------------------------------


def test_demo_service_creates_indexed_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    target = tmp_path / "demo-vault"
    result = demo_service.run_demo(target)
    assert (target / ".nexusos" / "workspace.json").is_file()
    assert (target / ".nexusos" / "index.sqlite3").is_file()
    assert result["status"]["status"] in ("ready", "stale")
    assert result["status"]["document_count"] >= 3
    assert result["steps"], "demo should record walkthrough steps"
    assert result["doctor_healthy"] is True


# ---------------------------------------------------------------------------
# L4 — real CLI invocations
# ---------------------------------------------------------------------------


def test_lint_cli_exit_zero_on_clean_repo(clean_repo_copy: Path) -> None:
    result = runner.invoke(app, ["lint", "--repo", str(clean_repo_copy)])
    assert result.exit_code == 0, result.output
    assert "All checks passed" in result.output


def test_lint_cli_invalid_tool_exits_two() -> None:
    result = runner.invoke(app, ["lint", "--tool", "bogus"])
    assert result.exit_code == 2
    assert "bogus" in result.output


def test_lint_cli_json_output(clean_repo_copy: Path) -> None:
    result = runner.invoke(app, ["lint", "--json", "--repo", str(clean_repo_copy)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "repo_root" in data
    assert "checks" in data
    assert data["has_findings"] is False


def test_demo_cli_walkthrough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    target = tmp_path / "demo-walkthrough"
    result = runner.invoke(app, ["demo", "--path", str(target)])
    assert result.exit_code == 0, result.output
    for marker in ("Step 1", "nexusos init", "nexusos index", "nexusos status", "Usage examples"):
        assert marker in result.output
    assert (target / "wiki" / "concepts" / "agents.md").is_file()
    assert (target / ".nexusos" / "index.sqlite3").is_file()


def test_demo_cli_remove_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    target = tmp_path / "demo-remove"
    result = runner.invoke(app, ["demo", "--path", str(target), "--remove"])
    assert result.exit_code == 0, result.output
    assert not target.exists()


def test_demo_cli_rejects_nonempty_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    target = tmp_path / "demo-nonempty"
    target.mkdir()
    (target / "existing.md").write_text("keep me", encoding="utf-8")
    result = runner.invoke(app, ["demo", "--path", str(target)])
    assert result.exit_code != 0
    assert "not empty" in result.output.lower() or "must be empty" in result.output.lower()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT subprocess smoke is POSIX-only")
def test_serve_cli_sigint_clean_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real ``nexusos serve`` subprocess: healthy HTTP, then SIGINT → clean exit 0."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = _make_workspace(tmp_path, monkeypatch)
    from nexusos.services.index_service import index_workspace

    index_workspace(ws)

    log_path = tmp_path / "serve.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    bootstrap = "from nexusos.cli.main import app; app()"
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-c", bootstrap, "serve", "--workspace", str(ws), "--port", "0"],
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        try:
            url: str | None = None
            text = ""
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                text = log_path.read_text(encoding="utf-8")
                match = re.search(r"http://127\.0\.0\.1:\d+", text)
                if match:
                    url = match.group(0)
                    break
                time.sleep(0.1)
            assert url is not None, f"server did not print bound URL; log:\n{text}"

            status, body = _http_get(f"{url}/healthz")
            assert status == 200
            assert json.loads(body)["ok"] is True

            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    assert proc.returncode == 0, f"serve exited {proc.returncode}; log:\n{text}"
    log = log_path.read_text(encoding="utf-8")
    assert "shutting down" in log.lower()
    assert "server stopped" in log.lower()

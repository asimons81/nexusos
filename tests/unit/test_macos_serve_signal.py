"""macOS subprocess smoke for clean inspection-server shutdown."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from nexusos.services.index_service import index_workspace
from nexusos.workspace.init import init_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific subprocess smoke")
def test_macos_serve_cli_sigint_clean_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cold-start the real CLI, prove health, and stop it with SIGINT."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    workspace = tmp_path / "ws"
    init_workspace(workspace, template="blank")
    (workspace / "note.md").write_text("# macOS serve smoke\n", encoding="utf-8")
    run = index_workspace(workspace)
    assert run.success

    log_path = tmp_path / "serve-macos.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONUNBUFFERED"] = "1"
    bootstrap = "from nexusos.cli.main import app; app()"

    text = ""
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                bootstrap,
                "serve",
                "--workspace",
                str(workspace),
                "--port",
                "0",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        try:
            url: str | None = None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                text = log_path.read_text(encoding="utf-8")
                match = re.search(r"http://127\.0\.0\.1:\d+", text)
                if match:
                    url = match.group(0)
                    break
                time.sleep(0.1)

            assert url is not None, f"server did not print bound URL; log:\n{text}"
            with urllib.request.urlopen(f"{url}/healthz", timeout=5) as response:
                assert response.status == 200
                payload = json.loads(response.read().decode("utf-8"))
                assert payload["ok"] is True

            process.send_signal(signal.SIGINT)
            process.wait(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    text = log_path.read_text(encoding="utf-8")
    assert process.returncode == 0, f"serve exited {process.returncode}; log:\n{text}"
    assert "shutting down" in text.lower()
    assert "server stopped" in text.lower()

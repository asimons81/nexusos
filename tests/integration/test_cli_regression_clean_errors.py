"""Regression tests: CLI errors degrade to clean ``Error:`` messages, not tracebacks.

F3 (probe t_50014353): the console entry point was the Typer ``app`` object, so
exceptions escaping ``config`` / ``init`` / ``serve`` rendered raw Rich
traceback panels with exit 1. These tests lock the fixed contract against the
real installed binary: a clean ``Error:`` line on stderr, the correct exit
code, and no ``Traceback`` anywhere in the output.

L4 layer: each test shells out to ``.venv/bin/nexusos`` (the shipped entry).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
NEXUSOS_BIN = REPO_ROOT / ".venv" / "bin" / "nexusos"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("NEXUSOS_DENY_PATHS", None)
    return env


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(NEXUSOS_BIN), *args],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(cwd),
        timeout=60,
    )


def _assert_clean_error(proc: subprocess.CompletedProcess[str], *, rc: int) -> None:
    combined = proc.stdout + proc.stderr
    assert proc.returncode == rc, (
        f"expected rc={rc}, got rc={proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "Traceback" not in combined, f"traceback leaked:\n{combined}"
    assert "Error:" in proc.stderr, f"no Error: line on stderr:\n{combined}"


def test_cli_regression_config_show_bad_toml_clean(tmp_path: Path) -> None:
    """`config show` on invalid TOML must exit 2 with a clean Error, no traceback.

    Before the fix this raised a Rich traceback panel with exit 1 (ConfigError
    escaped the `config` command; `index`/`search` already handled it cleanly).
    """
    ws = tmp_path / "ws"
    init = _run("init", str(ws), "--template", "blank", cwd=tmp_path)
    assert init.returncode == 0, init.stderr

    (ws / "nexusos.toml").write_text('[files\ninclude = ["**/*.md"]\n', encoding="utf-8")
    proc = _run("config", "show", "--workspace", str(ws), cwd=tmp_path)
    _assert_clean_error(proc, rc=2)
    assert "Invalid TOML" in proc.stderr, proc.stderr


def test_cli_regression_serve_bad_port_clean(tmp_path: Path) -> None:
    """`serve --port 99999` must exit 2 with a clean Error, no traceback.

    Before the fix this raised `OverflowError: bind(): port must be 0-65535`
    (the `except OSError` missed OverflowError).
    """
    ws = tmp_path / "ws"
    init = _run("init", str(ws), "--template", "blank", cwd=tmp_path)
    assert init.returncode == 0, init.stderr

    proc = _run(
        "serve", "--workspace", str(ws), "--host", "127.0.0.1", "--port", "99999", cwd=tmp_path
    )
    _assert_clean_error(proc, rc=2)
    assert "port" in proc.stderr.lower(), proc.stderr


def test_cli_regression_init_bad_path_clean(tmp_path: Path) -> None:
    """`init` at an existing file path must exit 1 with a clean Error, no traceback.

    Before the fix this raised `NotADirectoryError` (and `PermissionError` for a
    non-writable parent) as raw tracebacks.
    """
    victim = tmp_path / "target-file"
    victim.write_text("i am a file", encoding="utf-8")

    proc = _run("init", str(victim), cwd=tmp_path)
    _assert_clean_error(proc, rc=1)
    assert "initialize" in proc.stderr.lower(), proc.stderr


def test_cli_regression_stray_error_clean(tmp_path: Path) -> None:
    """Stray non-NexusOS errors must degrade to `unexpected error`, not a traceback.

    Acceptance backstop: the console entry routes through `main()`'s
    `except Exception`, so `index -w /nonexistent` (FileNotFoundError from
    Path.resolve(strict=True)) prints `nexusos: unexpected error: ...` and
    exits 1 instead of a Rich traceback panel.
    """
    missing = tmp_path / "does-not-exist"
    proc = _run("index", "--workspace", str(missing), cwd=tmp_path)
    assert proc.returncode == 1, (
        f"rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined, f"traceback leaked:\n{combined}"
    assert "unexpected error" in proc.stderr, proc.stderr

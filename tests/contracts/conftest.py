"""Shared fixtures and helpers for the A3-05 contract test suite.

The contract suite locks the public surface documented in docs/contracts.md:
CLI commands/options, exit codes, configuration/env contract, JSON shapes,
and MCP tool schemas. It shells out to the real ``nexusos`` entry point so
the tests exercise the shipped CLI, not just the Typer app object.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def nexusos_bin() -> Path:
    """Resolve the installed CLI entry point in this checkout.

    Prefer the repository virtualenv's script so tests exercise the shipped
    console entry; fall back to the current interpreter when the venv script
    is unavailable (e.g. CI environment without a local .venv).
    """
    candidates = (
        REPO_ROOT / ".venv" / "bin" / "nexusos",
        REPO_ROOT / ".venv" / "Scripts" / "nexusos.exe",
        REPO_ROOT / ".venv" / "Scripts" / "nexusos",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """A deterministic environment for CLI subprocesses.

    Strips PYTHONPATH (the host Hermes venv breaks pydantic_core) and any
    inherited NEXUSOS_* overrides so tests see a clean contract surface.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEXUSOS_")}
    env.pop("PYTHONPATH", None)
    if extra:
        env.update(extra)
    return env


def run_cli(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    """Run the real nexusos CLI and return the completed process."""
    bin_path = nexusos_bin()
    cmd = [str(bin_path), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=_clean_env(env),
        cwd=str(cwd or REPO_ROOT),
        timeout=timeout,
    )


def run_python_module(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m nexusos.mcp`` (the argparse MCP entry point)."""
    return subprocess.run(
        [sys.executable, "-m", "nexusos.mcp", *args],
        capture_output=True,
        text=True,
        env=_clean_env(env),
        cwd=str(cwd or REPO_ROOT),
        timeout=timeout,
    )


@pytest.fixture
def ws_path(tmp_path: Path) -> Path:
    """A fresh initialized workspace for contract tests."""
    ws = tmp_path / "ws"
    proc = run_cli("init", str(ws), "--template", "blank")
    assert proc.returncode == 0, f"init failed: {proc.stderr}"
    return ws

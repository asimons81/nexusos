"""Integration tests for the ``nexusos init`` CLI command (security-relevant paths).

Exercises the real CLI binary end-to-end. Covers the F-01 regression: a
pre-staged symlink at the old deterministic temp path (``.nexusos/workspace.json.tmp``)
must never redirect the identity write to an arbitrary victim file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

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


def test_cli_init_adopt_preseeded_symlink_safe(tmp_path: Path) -> None:
    """F-01: pre-staged symlink at .nexusos/workspace.json.tmp is not followed.

    The victim file must remain untouched and the CLI must fail cleanly
    (refuse to adopt a pre-seeded .nexusos/) rather than overwrite it.
    """
    ws = tmp_path / "ws"
    victim = tmp_path / "victim.txt"
    victim.write_text("VICTIM ORIGINAL DATA", encoding="utf-8")

    ws.mkdir()
    (ws / ".nexusos").mkdir()
    (ws / ".nexusos" / "workspace.json.tmp").symlink_to(victim)

    result = subprocess.run(
        [str(NEXUSOS_BIN), "init", str(ws), "--template", "blank", "--adopt"],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(tmp_path),
        timeout=60,
    )

    assert victim.read_text(encoding="utf-8") == "VICTIM ORIGINAL DATA"
    assert result.returncode != 0, (
        f"expected refusal, got rc=0 stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "refus" in (result.stdout + result.stderr).lower()


def test_cli_init_blank_ok(tmp_path: Path) -> None:
    """Sanity: a normal blank init through the real CLI still succeeds."""
    ws = tmp_path / "ws"
    result = subprocess.run(
        [str(NEXUSOS_BIN), "init", str(ws), "--template", "blank"],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(tmp_path),
        timeout=60,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert (ws / ".nexusos" / "workspace.json").is_file()

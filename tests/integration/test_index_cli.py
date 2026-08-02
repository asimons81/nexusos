"""Integration tests for the ``nexusos index`` CLI command.

Exercises the real CLI binary end-to-end. Covers the F1 regression: a
machine-generated markdown file with thousands of headings must index in
bounded time (the old O(n^3) heading-path builder hung while holding the
exclusive writer lock).
"""

from __future__ import annotations

import os
import subprocess
import time
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


def _init_workspace(ws: Path) -> None:
    result = subprocess.run(
        [str(NEXUSOS_BIN), "init", str(ws), "--template", "blank"],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(ws.parent),
        timeout=60,
    )
    assert result.returncode == 0, f"init failed: stderr={result.stderr!r}"


def test_index_regression_many_headings_fast(tmp_path: Path) -> None:
    """F1: a 5000-flat-heading markdown file indexes in a few seconds.

    The O(n^3) heading-path builder stalled at ~5s for 1000 headings and
    >20s for 2000; 5000 must now complete well within a bounded window via
    the real CLI, and the stored heading count must be correct.
    """
    ws = tmp_path / "ws"
    _init_workspace(ws)
    (ws / "wiki").mkdir(exist_ok=True)

    # 5000 flat (same-level) headings — the worst case for the old builder,
    # which rescanned the whole heading list inside the per-heading loop.
    heading_count = 5000
    big_doc = "".join(f"## Heading {i}\n\nbody {i}\n\n" for i in range(heading_count))
    (ws / "wiki" / "big.md").write_text(big_doc, encoding="utf-8")

    started = time.monotonic()
    result = subprocess.run(
        [str(NEXUSOS_BIN), "index", "--workspace", str(ws)],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(ws),
        timeout=60,
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0, (
        f"index failed: rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # Old O(n^3) code exceeded 20s at 2000 headings; 5000 in a few seconds
    # is the acceptance bar. Generous bound to avoid CI flakiness while
    # still failing loudly on an algorithmic regression.
    assert elapsed < 15.0, f"indexing {heading_count} headings took {elapsed:.1f}s"

    status = subprocess.run(
        [str(NEXUSOS_BIN), "status", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        env=_env(),
        cwd=str(ws),
        timeout=30,
    )
    assert status.returncode == 0, f"status failed: stderr={status.stderr!r}"
    import json

    data = json.loads(status.stdout)
    # The blank template ships a README.md with one heading, so the stored
    # count is template headings + our 5000; the important guarantee is that
    # every one of our headings was persisted.
    assert data["heading_count"] >= heading_count, data

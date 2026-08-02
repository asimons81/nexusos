"""Integration tests for end-to-end indexing pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nexusos.core.config import load_config_effective
from nexusos.indexing.indexer import run_index
from nexusos.indexing.kernel import IndexKernel
from nexusos.services.status_service import get_status

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "golden"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    dest = tmp_path / "golden"
    shutil.copytree(FIXTURE_ROOT, dest, symlinks=True)
    # Bootstrap workspace identity (bypass init to keep test fast)
    nexusos_dir = dest / ".nexusos"
    nexusos_dir.mkdir(exist_ok=True)
    identity = {
        "schema_version": 1,
        "workspace_id": "nxo_ws_testfixture",
        "created_at": "2026-01-01T00:00:00+00:00",
        "nexusos_version": "0.1.0",
    }
    (nexusos_dir / "workspace.json").write_text(json.dumps(identity))
    return dest


class TestEndToEndIndex:
    def test_full_index(self, ws: Path) -> None:
        config = load_config_effective(ws)
        run = run_index(ws, config, full=True)
        assert run.success is True
        assert run.files_added >= 5

    def test_incremental_noop(self, ws: Path) -> None:
        config = load_config_effective(ws)
        run1 = run_index(ws, config, full=True)
        assert run1.success

        run2 = run_index(ws, config, full=False)
        assert run2.success
        assert run2.files_added == 0
        assert run2.files_unchanged == run1.files_added

    def test_link_resolution(self, ws: Path) -> None:
        config = load_config_effective(ws)
        run = run_index(ws, config, full=True)
        assert run.success

        kernel = IndexKernel(ws)
        kernel.open()
        try:
            gpg = kernel.get_document("wiki/golden-page.md")
            assert gpg is not None
            assert len(gpg.wikilinks) >= 1
        finally:
            kernel.close()

    def test_status_after_index(self, ws: Path) -> None:
        config = load_config_effective(ws)
        run = run_index(ws, config, full=True)
        assert run.success

        status = get_status(ws)
        assert status["status"] == "ready"
        assert status["document_count"] >= 5
        assert status["chunk_count"] >= 1

    def test_config_fingerprint_staleness(self, ws: Path) -> None:
        config = load_config_effective(ws)
        run_index(ws, config, full=True)

        toml_path = ws / "nexusos.toml"
        original = toml_path.read_text()
        modified = original.replace("chunk_max_chars = 2400", "chunk_max_chars = 9999")
        toml_path.write_text(modified)
        try:
            status = get_status(ws)
            assert status["stale"] is True
            assert any("config fingerprint" in r for r in status["stale_reasons"])
        finally:
            toml_path.write_text(original)

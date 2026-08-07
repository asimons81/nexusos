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

    def test_incremental_noop_avoids_full_document_assembly(
        self, ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MED-5: a no-op incremental pass must use signatures and must not
        reassemble full documents (bounded assembly count, deterministic in CI).

        Baseline behavior performs ~2N full document assemblies — one per
        common path in the change-detection fast path and one per document in
        the link-resolution phase. The fix reads lightweight mtime/size
        signatures and persisted links instead, so a no-op pass performs zero
        full document assemblies.
        """
        from nexusos.indexing.database import IndexDatabase
        from nexusos.indexing.models import IndexedDocument

        config = load_config_effective(ws)
        run1 = run_index(ws, config, full=True)
        assert run1.success

        calls = 0
        original = IndexDatabase._assemble_document

        def counting(self: IndexDatabase, document_id: str) -> IndexedDocument | None:
            nonlocal calls
            calls += 1
            return original(self, document_id)

        monkeypatch.setattr(IndexDatabase, "_assemble_document", counting)

        run2 = run_index(ws, config, full=False)
        assert run2.success
        assert run2.files_unchanged == run1.files_added
        assert calls == 0


def test_index_regression_heading_paths_preserved(tmp_path: Path) -> None:
    """L2: run_index persists correct ancestor heading paths (F1 regression).

    The O(n) rewrite must not change the stored heading-path values: a nested
    document keeps its ancestor chain in the headings table exactly as before.
    """
    import json

    from nexusos.indexing.kernel import IndexKernel

    ws = tmp_path / "paths"
    ws.mkdir()
    nexusos_dir = ws / ".nexusos"
    nexusos_dir.mkdir(exist_ok=True)
    identity = {
        "schema_version": 1,
        "workspace_id": "nxo_ws_paths",
        "created_at": "2026-01-01T00:00:00+00:00",
        "nexusos_version": "0.1.0",
    }
    (nexusos_dir / "workspace.json").write_text(json.dumps(identity))

    (ws / "nexusos.toml").write_text(
        "[files]\n"
        'include = ["**/*.md"]\n'
        "\n"
        "[indexing]\n"
        "chunk_max_chars = 2400\n"
        "chunk_overlap_chars = 200\n"
    )
    (ws / "wiki").mkdir()
    (ws / "wiki" / "nested.md").write_text(
        "# Top\n\n## Mid\n\n### Deep\n\nbody\n\n## Sibling\n\nbody\n",
        encoding="utf-8",
    )

    config = load_config_effective(ws)
    run = run_index(ws, config, full=True)
    assert run.success is True
    assert run.files_added == 1

    kernel = IndexKernel(ws)
    kernel.open()
    try:
        doc = kernel.get_document("wiki/nested.md")
        assert doc is not None
        paths = {h.ordinal: h.heading_path for h in doc.headings}
        assert paths == {
            1: ("Top",),
            2: ("Top", "Mid"),
            3: ("Top", "Mid", "Deep"),
            4: ("Top", "Sibling"),
        }
    finally:
        kernel.close()


def test_config_change_forces_rechunk(tmp_path: Path) -> None:
    """MED-4: a chunk-affecting config edit must re-chunk documents on the next
    incremental pass (config fingerprint invalidation).

    Regression for audit finding MED-4: the stored config fingerprint was never
    used to force re-parsing, so changing ``chunk_max_chars`` silently did not
    re-chunk until a manual ``--full`` run. The stored fingerprint is expected
    to invalidate derived state: a changed fingerprint forces reprocessing of
    every common path (safe full reparse).
    """
    from nexusos.indexing.kernel import IndexKernel

    ws = tmp_path / "rechunk"
    ws.mkdir()
    nexusos_dir = ws / ".nexusos"
    nexusos_dir.mkdir(exist_ok=True)
    identity = {
        "schema_version": 1,
        "workspace_id": "nxo_ws_rechunk",
        "created_at": "2026-01-01T00:00:00+00:00",
        "nexusos_version": "0.1.0",
    }
    (nexusos_dir / "workspace.json").write_text(json.dumps(identity))
    (ws / "nexusos.toml").write_text(
        "[files]\n"
        'include = ["**/*.md"]\n'
        "\n"
        "[indexing]\n"
        "chunk_max_chars = 2400\n"
        "chunk_overlap_chars = 200\n"
    )
    (ws / "wiki").mkdir()
    body = "\n\n".join(f"Paragraph {i} with some filler text for chunking." for i in range(400))
    (ws / "wiki" / "big.md").write_text(f"# Big\n\n{body}\n", encoding="utf-8")

    config1 = load_config_effective(ws)
    run1 = run_index(ws, config1, full=True)
    assert run1.success

    kernel = IndexKernel(ws)
    kernel.open()
    try:
        doc = kernel.get_document("wiki/big.md")
        assert doc is not None
        chunks_before = len(doc.chunks)
    finally:
        kernel.close()
    assert chunks_before >= 2

    # Change a chunk-affecting config value WITHOUT touching any source file.
    toml_path = ws / "nexusos.toml"
    toml_path.write_text(
        toml_path.read_text().replace("chunk_max_chars = 2400", "chunk_max_chars = 300")
    )

    config2 = load_config_effective(ws)
    run2 = run_index(ws, config2, full=False)  # incremental
    assert run2.success
    # The stored fingerprint differs, so the common path is reprocessed.
    assert run2.files_updated >= 1

    kernel = IndexKernel(ws)
    kernel.open()
    try:
        doc = kernel.get_document("wiki/big.md")
        assert doc is not None
        chunks_after = len(doc.chunks)
    finally:
        kernel.close()
    assert chunks_after > chunks_before

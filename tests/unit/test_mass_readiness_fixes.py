"""Regression tests for mass-readiness audit fixes (kanban task t_be4bf164).

Locks three verified findings on origin/main 1af3f36:

- HIGH-1: ``.markdown`` sources are silently excluded by the default include
  patterns even though the scanner advertises them as indexed extensions.
- HIGH-2: wiki-link suffix precedence diverges between index-time graph
  resolution and kernel navigation lookup; the canonical order is ``.md``
  first so both surfaces agree.
- MED-3: vault lint crashes on invalid UTF-8 source files instead of
  producing a structured, clean report.

Synthetic fixtures only; no personal paths, no network access.
"""

from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003

import pytest  # noqa: TC002

from nexusos.core.config import load_config_effective
from nexusos.core.models import DEFAULT_CONFIG, WorkspaceIdentity
from nexusos.discovery.scanner import scan_workspace
from nexusos.indexing.graph import resolve_links
from nexusos.indexing.ids import chunk_id, document_id
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import (
    IndexedChunk,
    IndexedDocument,
    IndexedLink,
)
from nexusos.services.vault_lint_service import run_vault_lint
from nexusos.workspace.init import init_workspace

_WS = "nxo_ws_mass_readiness"


def _identity() -> WorkspaceIdentity:
    return WorkspaceIdentity(
        workspace_id=_WS,
        created_at="2026-01-01T00:00:00Z",
        nexusos_version="0.1.0",
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _make_doc(
    workspace_id: str,
    relative_path: str,
    *,
    wikilinks: list[IndexedLink] | None = None,
) -> IndexedDocument:
    """Build a minimal IndexedDocument for kernel/graph tests."""
    normalized_path = relative_path.replace("\\", "/")
    doc_id = document_id(workspace_id, normalized_path)
    body_text = f"{normalized_path} body"
    body_sha = _sha(body_text)
    chunk = IndexedChunk(
        chunk_id=chunk_id(doc_id, 1, body_sha),
        document_id=doc_id,
        ordinal=1,
        heading_path=("Doc",),
        start_line=1,
        end_line=2,
        text=body_text,
        content_sha256=body_sha,
    )
    return IndexedDocument(
        document_id=doc_id,
        relative_path=normalized_path,
        normalized_path=normalized_path,
        collection="wiki",
        title="Doc",
        file_type="markdown",
        authority_class="unknown",
        mtime_ns=1_700_000_000_000_000_000,
        size_bytes=100,
        content_sha256=_sha("content"),
        frontmatter_json="{}",
        indexed_at="2026-01-01T00:00:00+00:00",
        line_count=2,
        headings=[],
        chunks=[chunk],
        wikilinks=wikilinks or [],
        tags=[],
    )


def _write(ws: Path, rel: str, text: str) -> None:
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# -- HIGH-1: .markdown included by default -----------------------------------


def test_default_config_includes_markdown_pattern() -> None:
    """The default include list must not silently drop .markdown sources."""
    assert "**/*.markdown" in DEFAULT_CONFIG.include_patterns


def test_scan_workspace_discovers_markdown_by_default(tmp_path: Path) -> None:
    """A .markdown-only file is discovered under default config."""
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    _write(ws, "only.markdown", "# Only Markdown\n")
    _write(ws, "notes.txt", "plain text\n")

    config = load_config_effective(ws)
    result = scan_workspace(ws, config)
    paths = {f.normalized_path for f in result.files}

    assert "only.markdown" in paths
    assert "notes.txt" in paths


def test_index_workspace_indexes_markdown_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Indexing a fresh workspace includes .markdown sources (HIGH-1 probe A4)."""
    from nexusos.services.index_service import index_workspace

    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    _write(ws, "only.markdown", "# Only Markdown\n\nBody.\n")

    run = index_workspace(ws, full=True)

    assert run.success
    # blank template contributes README.md; only.markdown must also be seen.
    paths = {f.normalized_path for f in scan_workspace(ws, load_config_effective(ws)).files}
    assert "only.markdown" in paths
    assert run.files_seen == 2


# -- HIGH-2: canonical wiki-link suffix precedence ---------------------------


def test_canonical_link_suffix_order_is_md_first() -> None:
    """One shared constant defines the canonical suffix order (.md first)."""
    from nexusos.core.link_suffixes import LINK_SUFFIXES

    assert LINK_SUFFIXES == (".md", ".markdown", ".txt")


def test_graph_and_kernel_agree_on_md_markdown_collision(tmp_path: Path) -> None:
    """Graph resolution and navigation lookup pick the same document.

    With both ``foo.md`` and ``foo.markdown`` present, ``[[foo]]`` and
    ``nexusos read foo`` must agree (HIGH-2 probe A5). Canonical order is
    ``.md`` first.
    """
    k = IndexKernel(tmp_path, identity=_identity())
    k.open(create_parent=True)
    try:
        md_id = document_id(_WS, "foo.md")
        k.add_document(_make_doc(_WS, "foo.md"))
        k.add_document(_make_doc(_WS, "foo.markdown"))

        # Navigation lookup (read/links/context) resolves the stem.
        candidates = k.lookup_candidates("foo")
        assert [c.normalized_path for c in candidates] == ["foo.md"]

        # Index-time graph resolution of [[foo]] targets the same document.
        linker = _make_doc(
            _WS,
            "linker.md",
            wikilinks=[IndexedLink(source_line=1, raw_target="foo", target_slug="foo")],
        )
        k.add_document(linker)
        resolved = resolve_links(
            k,
            [(linker.document_id, linker.wikilinks)],
            all_document_ids={
                md_id,
                document_id(_WS, "foo.markdown"),
                linker.document_id,
            },
        )
        link = resolved[0][1][0]
        assert link.target_document_id == md_id
        assert link.resolution_state == "resolved"
    finally:
        k.close()


# -- MED-3: vault lint handles invalid UTF-8 cleanly -------------------------


def test_vault_lint_does_not_crash_on_invalid_utf8(tmp_path: Path) -> None:
    """A malformed UTF-8 source file yields a structured finding, not a crash."""
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    bad = ws / "wiki" / "bad.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"# Bad\n\nok\n\xff\xfe bad\n")

    report = run_vault_lint(ws)  # must not raise

    assert report.workspace == str(ws.resolve(strict=False))
    assert len(report.checks) > 0
    assert all(c.status in ("pass", "warn", "fail") for c in report.checks)
    # The malformed file is reported as an unreadable-file finding so the
    # failure is structured and the run does not abort mid-way.
    unreadable = next(c for c in report.checks if c.name == "unreadable-files")
    assert unreadable.status == "fail"
    assert any(f.path == "wiki/bad.md" for f in unreadable.findings)


# -- templates ---------------------------------------------------------------


def test_workspace_templates_include_markdown_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both starter and blank templates advertise the .markdown include."""
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    for template in ("blank", "starter"):
        ws = tmp_path / template
        init_workspace(ws, template=template)
        config = (ws / "nexusos.toml").read_text(encoding="utf-8")
        assert "**/*.markdown" in config, f"{template} template missing .markdown include"

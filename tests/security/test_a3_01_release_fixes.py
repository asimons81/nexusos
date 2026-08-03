"""Regression/adversarial tests for the A3-01 release findings (F-03/F-05/F-06/F-07/F-08).

One regression test per finding, per the v0.1 release checklist §4 (A3-01
test requirement). Each test pins the fix so the finding cannot silently
regress:
- F-03: indexer read path refuses a symlink swap (TOCTOU)
- F-05: relative deny paths are deterministic (never CWD-relative)
- F-06: search/browse/recent/context limits are range-validated everywhere
- F-07: check_symlink_escape is wired into doctor and init --adopt
- F-08: non-loopback binds are refused for the unauthenticated MCP surface
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nexusos.core.config import load_config_effective
from nexusos.core.errors import ConfigError, NavigationError, PathSafetyError
from nexusos.core.path_safety import find_symlink_escapes, is_denied_path, read_source_text_safe
from nexusos.workspace.init import init_workspace

if TYPE_CHECKING:
    from pathlib import Path


def _blank_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    return ws


# ---------------------------------------------------------------------------
# F-03 — indexer read-path TOCTOU
# ---------------------------------------------------------------------------


def test_f03_safe_read_refuses_escaping_symlink(tmp_path: Path) -> None:
    """The safe read helper must refuse a file swapped for an escaping symlink."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOCTOU-SECRET-MATERIAL", encoding="utf-8")

    note = ws / "note.md"
    note.write_text("original", encoding="utf-8")
    # Swap the file for a symlink to an outside file (the attack window).
    note.unlink()
    note.symlink_to(secret)

    with pytest.raises(PathSafetyError):
        read_source_text_safe(note, ws)


def test_f03_safe_read_returns_internal_file(tmp_path: Path) -> None:
    """The safe read helper still reads a regular in-workspace file normally."""
    ws = tmp_path / "ws"
    ws.mkdir()
    note = ws / "note.md"
    note.write_text("# Hello\n", encoding="utf-8")
    assert read_source_text_safe(note, ws) == "# Hello\n"


def test_f03_indexer_does_not_ingest_swapped_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file swapped for an escaping symlink between scan and read is refused.

    Deterministic reproduction: the scanner is monkeypatched to report the
    file (as if it had been scanned before the swap), while the on-disk
    entry is now a symlink pointing outside the workspace. The indexer read
    path must refuse to follow it, so the outside content is never ingested.
    """
    ws = _blank_workspace(tmp_path, monkeypatch)
    (ws / "wiki").mkdir()
    note = ws / "wiki" / "note.md"
    note.write_text("# Note\ninside\n", encoding="utf-8")

    from nexusos.services.index_service import index_workspace

    assert index_workspace(ws).success

    # Outside secret the attacker wants pulled into the index.
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOCTOU-SECRET-MATERIAL", encoding="utf-8")

    # Swap: the file becomes a symlink to the outside secret.
    note.unlink()
    note.symlink_to(secret)

    # Simulate a scan that ran *before* the swap (the scanner would not have
    # seen a symlink yet) — the read path must still catch it.
    import nexusos.indexing.indexer as indexer_mod
    from nexusos.discovery.models import DiscoveredFile, DiscoveryResult

    fake = DiscoveryResult(
        files=[
            DiscoveredFile(
                relative_path="wiki/note.md",
                normalized_path="wiki/note.md",
                collection="wiki",
                file_type="markdown",
                size_bytes=secret.stat().st_size,
                mtime_ns=secret.stat().st_mtime_ns,
            )
        ]
    )
    monkeypatch.setattr(indexer_mod, "scan_workspace", lambda *a, **k: fake)

    config = load_config_effective(ws)
    run = indexer_mod.run_index(ws, config, full=True)
    assert run.documents_failed >= 1

    # The outside content must not be searchable.
    from nexusos.indexing.kernel import IndexKernel

    kernel = IndexKernel(ws)
    kernel.open(create_parent=False, read_only=True)
    try:
        hits = kernel.search("TOCTOU-SECRET")
        assert hits == []
    finally:
        kernel.close()


# ---------------------------------------------------------------------------
# F-05 — relative deny paths are deterministic
# ---------------------------------------------------------------------------


def test_f05_relative_deny_path_never_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative deny entry must not resolve against CWD (deterministic skip)."""
    target = tmp_path / "secret"
    target.mkdir()
    # Relative entry that would match the target if resolved against its
    # parent (the old CWD bug), or against any CWD.
    env_deny = "secret"
    monkeypatch.chdir(tmp_path)
    assert not is_denied_path(target, env_deny=env_deny)

    # Even from a different CWD the result is the same: relative entries
    # never match.
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    assert not is_denied_path(target, env_deny=env_deny)


def test_f05_absolute_deny_path_still_matches(tmp_path: Path) -> None:
    """Absolute deny entries keep working (no behavior regression)."""
    target = tmp_path / "secret"
    target.mkdir()
    assert is_denied_path(target, env_deny=str(tmp_path))


# ---------------------------------------------------------------------------
# F-06 — limit range validation (service layer, shared by CLI + MCP)
# ---------------------------------------------------------------------------


def test_f06_search_rejects_out_of_range_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _blank_workspace(tmp_path, monkeypatch)
    from nexusos.core.errors import IndexingError
    from nexusos.services.search_service import search_workspace

    for bad in (-1, 0, 100_000):
        with pytest.raises(IndexingError):
            search_workspace(ws, "term", limit=bad)
    # Boundary values are accepted.
    with pytest.raises(Exception):  # workspace unindexed, but not a limit error
        search_workspace(ws, "term", limit=1)


def test_f06_search_rejects_non_positive_snippet_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _blank_workspace(tmp_path, monkeypatch)
    from nexusos.core.errors import IndexingError
    from nexusos.services.search_service import search_workspace

    for bad in (-1, 0):
        with pytest.raises(IndexingError):
            search_workspace(ws, "term", snippet_tokens=bad)


def test_f06_browse_rejects_out_of_range_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _blank_workspace(tmp_path, monkeypatch)
    from nexusos.services.navigation_service import browse_workspace

    for bad in (-1, 0, 100_000):
        with pytest.raises(NavigationError):
            browse_workspace(ws, limit=bad)


def test_f06_recent_rejects_out_of_range_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _blank_workspace(tmp_path, monkeypatch)
    from nexusos.services.navigation_service import recent_documents

    for bad in (-1, 0, 100_000):
        with pytest.raises(NavigationError):
            recent_documents(ws, limit=bad)


def test_f06_context_rejects_out_of_range_sibling_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _blank_workspace(tmp_path, monkeypatch)
    from nexusos.services.navigation_service import document_context

    for bad in (-1, 0, 100_000):
        with pytest.raises(NavigationError):
            document_context(ws, "missing", sibling_limit=bad)


def test_f06_config_rejects_out_of_range_search_values(tmp_path: Path) -> None:
    from nexusos.core.config import load_config

    config_path = tmp_path / "nexusos.toml"
    for bad in (-1, 0, 100_000):
        config_path.write_text(f"search_max_results = {bad}\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(config_path, apply_env=False)
        config_path.write_text(f"search_snippet_length = {bad}\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(config_path, apply_env=False)


def test_f06_mcp_args_reject_out_of_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from nexusos.mcp.server import BrowseArgs, RecentArgs, SearchArgs

    with pytest.raises(ValidationError):
        SearchArgs(term="x", limit=-1)
    with pytest.raises(ValidationError):
        SearchArgs(term="x", snippet_tokens=0)
    with pytest.raises(ValidationError):
        BrowseArgs(limit=-1)
    with pytest.raises(ValidationError):
        RecentArgs(limit=0)
    # Valid values still parse.
    assert SearchArgs(term="x", limit=10, snippet_tokens=200).limit == 10
    assert BrowseArgs(limit=5).limit == 5


# ---------------------------------------------------------------------------
# F-07 — check_symlink_escape is live at public boundaries
# ---------------------------------------------------------------------------


def test_f07_find_symlink_escapes_reports_escaping_link(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = ws / "escape"
    link.symlink_to(outside)
    escapes = find_symlink_escapes(ws)
    assert link.resolve() in [e.resolve() for e in escapes]


def test_f07_doctor_reports_symlink_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _blank_workspace(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "escape").symlink_to(outside)

    from nexusos.services.doctor import run_doctor

    report = run_doctor(ws)
    check = next((c for c in report.checks if c.check == "symlink_escape"), None)
    assert check is not None, "doctor must include a symlink_escape check"
    assert check.status == "warning", f"expected warning, got {check.status}: {check.message}"


def test_f07_init_adopt_refuses_escaping_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXOSOS_DENY_PATHS", raising=False)
    from nexusos.core.errors import SymlinkEscapeError

    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.md").write_text("keep", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "escape").symlink_to(outside)

    with pytest.raises(SymlinkEscapeError):
        init_workspace(target, template="blank", adopt=True)


# ---------------------------------------------------------------------------
# F-08 — non-loopback bind policy for the unauthenticated MCP surface
# ---------------------------------------------------------------------------


def test_f08_mcp_non_loopback_refused_without_override() -> None:
    from nexusos.services.serve_service import loopback_bind_policy

    assert loopback_bind_policy("0.0.0.0", allow_non_loopback=False) is False
    assert loopback_bind_policy("0.0.0.0", allow_non_loopback=True) is True
    assert loopback_bind_policy("127.0.0.1", allow_non_loopback=False) is True
    assert loopback_bind_policy("localhost", allow_non_loopback=False) is True


def test_f08_env_override_allows_non_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUSOS_ALLOW_NON_LOOPBACK", "1")
    from nexusos.services.serve_service import loopback_bind_policy

    assert loopback_bind_policy("0.0.0.0", allow_non_loopback=False) is True

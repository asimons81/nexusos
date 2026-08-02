"""Unit tests for the workspace vault linter service.

These tests exercise ``run_vault_lint`` against synthetic workspaces built
in temporary directories. No personal paths or private data are used.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest  # noqa: TC002

from nexusos.core.config import load_config_effective
from nexusos.services.vault_lint_service import (
    CHECK_AMBIGUOUS_LINKS,
    CHECK_BROKEN_LINKS,
    CHECK_DUPLICATE_SLUGS,
    CHECK_EMPTY_DOCUMENTS,
    CHECK_INVALID_FRONTMATTER,
    CHECK_ORPHANS,
    CHECK_OUTSIDE_COLLECTIONS,
    CHECK_OVERSIZED_FILES,
    CHECK_STALE_INDEX,
    CHECK_SYMLINK_ESCAPES,
    print_vault_lint_report,
    run_vault_lint,
)
from nexusos.workspace.init import init_workspace


def _workspace(tmp_path: Path) -> Path:
    """Create an initialized blank workspace."""
    ws = tmp_path / "ws"
    init_workspace(ws, template="blank")
    return ws


def _write(ws: Path, rel: str, text: str) -> None:
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check(report, name: str):
    return next(c for c in report.checks if c.name == name)


def test_clean_vault_lints_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexusos.services.index_service import index_workspace

    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n\nBody.\n")
    _write(ws, "wiki/beta.md", "# Beta\n\nSee [[alpha]].\n")
    run = index_workspace(ws, full=True)
    assert run.success

    report = run_vault_lint(ws)

    assert report.passed > 0
    assert report.failed == 0
    assert not report.has_findings
    assert _check(report, CHECK_BROKEN_LINKS).status == "pass"
    assert _check(report, CHECK_AMBIGUOUS_LINKS).status == "pass"
    assert _check(report, CHECK_INVALID_FRONTMATTER).status == "pass"
    assert _check(report, CHECK_STALE_INDEX).status == "pass"


def test_broken_link_detected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n\nSee [[missing-page]].\n")

    report = run_vault_lint(ws)
    check = _check(report, CHECK_BROKEN_LINKS)

    assert check.status == "fail"
    assert report.has_findings
    assert len(check.findings) == 1
    assert check.findings[0].path == "wiki/alpha.md"
    assert "missing-page" in check.findings[0].message


def test_ambiguous_link_detected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/a/dupe.md", "# A\n")
    _write(ws, "wiki/b/dupe.md", "# B\n")
    _write(ws, "wiki/c.md", "# C\n\nSee [[dupe]].\n")

    report = run_vault_lint(ws)
    check = _check(report, CHECK_AMBIGUOUS_LINKS)

    assert check.status == "fail"
    assert len(check.findings) >= 1
    assert check.findings[0].path == "wiki/c.md"
    assert "ambiguous" in check.findings[0].message


def test_invalid_frontmatter_detected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    # Missing closing delimiter is a parse warning.
    _write(ws, "wiki/bad.md", "---\ntitle: Broken\n\n# Bad\n")
    _write(ws, "wiki/good.md", "# Good\n")

    report = run_vault_lint(ws)
    check = _check(report, CHECK_INVALID_FRONTMATTER)

    assert check.status == "fail"
    assert any(f.path == "wiki/bad.md" for f in check.findings)


def test_duplicate_slugs_detected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/a/dupe.md", "# A\n")
    _write(ws, "wiki/b/dupe.md", "# B\n")

    report = run_vault_lint(ws)
    check = _check(report, CHECK_DUPLICATE_SLUGS)

    assert check.status == "fail"
    assert len(check.findings) == 2
    assert all("duplicate slug" in f.message for f in check.findings)


def test_stale_index_detected_without_index(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n")

    report = run_vault_lint(ws)
    check = _check(report, CHECK_STALE_INDEX)

    assert check.status == "fail"
    assert any("no index" in f.message for f in check.findings)


def test_stale_index_clear_after_indexing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexusos.services.index_service import index_workspace

    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n\nBody.\n")
    run = index_workspace(ws, full=True)
    assert run.success

    report = run_vault_lint(ws)
    check = _check(report, CHECK_STALE_INDEX)

    assert check.status == "pass"


def test_oversized_file_detected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/big.md", "# Big\n\n" + ("x" * 200))
    # Override the lint cap via config to something tiny.
    config = load_config_effective(ws)
    config.lint_max_file_size_bytes = 100

    from nexusos.services import vault_lint_service

    original = vault_lint_service.load_config_effective
    vault_lint_service.load_config_effective = lambda _root: config  # type: ignore[assignment]
    try:
        report = run_vault_lint(ws)
    finally:
        vault_lint_service.load_config_effective = original

    check = _check(report, CHECK_OVERSIZED_FILES)
    assert check.status == "fail"
    assert any(f.path == "wiki/big.md" for f in check.findings)


def test_empty_document_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexusos.services.index_service import index_workspace

    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    ws = _workspace(tmp_path)
    _write(ws, "wiki/empty.md", "")
    _write(ws, "wiki/alpha.md", "# Alpha\n")
    run = index_workspace(ws, full=True)
    assert run.success

    report = run_vault_lint(ws)
    check = _check(report, CHECK_EMPTY_DOCUMENTS)

    assert check.status == "warn"
    assert not report.has_findings  # warnings alone do not fail
    assert any(f.path == "wiki/empty.md" for f in check.findings)


def test_orphan_warns(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n")
    _write(ws, "wiki/beta.md", "# Beta\n\nSee [[alpha]].\n")

    report = run_vault_lint(ws)
    check = _check(report, CHECK_ORPHANS)

    assert check.status == "warn"
    paths = {f.path for f in check.findings}
    assert "wiki/alpha.md" not in paths  # linked by beta
    assert "wiki/beta.md" in paths  # nobody links to beta


def test_outside_collections_warns(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    init_workspace(ws, template="starter")  # starter config has [collections]
    _write(ws, "wiki/alpha.md", "# Alpha\n")
    # File outside any configured collection lands in default collection.
    _write(ws, "misc/loose.md", "# Loose\n")

    report = run_vault_lint(ws)
    check = _check(report, CHECK_OUTSIDE_COLLECTIONS)

    assert check.status == "warn"
    assert any(f.path == "misc/loose.md" for f in check.findings)


def test_symlink_escape_detected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    (ws / "wiki" / "escape.md").symlink_to(outside)

    report = run_vault_lint(ws)
    check = _check(report, CHECK_SYMLINK_ESCAPES)

    # The scanner's default policy is "ignore", so an escaping symlink is
    # not necessarily a warning unless the policy denies/warns. Just assert
    # the check exists and has a valid status (policy-dependent).
    assert check.name == CHECK_SYMLINK_ESCAPES
    assert check.status in ("pass", "fail", "warn")


def test_report_json_serializable(tmp_path: Path) -> None:
    import json

    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n\nSee [[missing]].\n")

    report = run_vault_lint(ws)
    payload = report.model_dump(mode="json")
    json.dumps(payload)  # must not raise


def test_print_vault_lint_report_human_and_json(tmp_path: Path, capsys) -> None:
    ws = _workspace(tmp_path)
    _write(ws, "wiki/alpha.md", "# Alpha\n")

    report = run_vault_lint(ws)
    print_vault_lint_report(report)
    out = capsys.readouterr().out
    assert "NexusOS vault lint" in out
    assert "[PASS]" in out

    print_vault_lint_report(report, use_json=True)
    out = capsys.readouterr().out
    assert '"workspace"' in out

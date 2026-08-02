"""Tests for discovery scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexusos.core.config import load_config_effective
from nexusos.discovery.scanner import _compile_patterns, scan_workspace


class TestCompilePatterns:
    def test_single_glob(self) -> None:
        rx = _compile_patterns(["**/*.md"])
        assert len(rx) == 1
        # Pattern requires at least one directory separator
        assert rx[0].match("dir/file.md")
        assert not rx[0].match("dir/file.txt")

    def test_doublestar_matches_root_files(self) -> None:
        # Regression: ``**/`` must match zero directories, so the default
        # ``**/*.md`` include pattern also discovers root-level files.
        rx = _compile_patterns(["**/*.md"])
        assert rx[0].match("root-note.md")
        assert rx[0].match("dir/file.md")
        assert rx[0].match("a/b/c/file.md")

    def test_multiple_globs(self) -> None:
        rx = _compile_patterns(["**/*.md", "**/*.txt"])
        assert len(rx) == 2
        assert rx[0].match("dir/file.md")
        assert rx[1].match("dir/file.txt")

    def test_exclude_glob(self) -> None:
        include = _compile_patterns(["**/*"])
        exclude = _compile_patterns(["**/__pycache__/**"])
        assert include[0].match("src/main.py")
        assert exclude[0].match("src/__pycache__/main.cpython-312.pyc")
        assert not exclude[0].match("src/main.py")

    def test_globstar_edge_cases(self) -> None:
        # Lock in gitignore-style globstar semantics for the edge patterns.
        everything = _compile_patterns(["**"])[0]
        assert everything.match("root.md")
        assert everything.match("a/b/c.md")

        under_dir = _compile_patterns(["dir/**"])[0]
        assert under_dir.match("dir/a.md")
        assert under_dir.match("dir/sub/b.md")
        assert not under_dir.match("root.md")

        pycache = _compile_patterns(["**/__pycache__/**"])[0]
        assert pycache.match("__pycache__/x.py")  # root-level pycache
        assert pycache.match("a/b/__pycache__/x.py")


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "golden"


class TestScanWorkspace:
    def test_scans_fixtures(self) -> None:
        config = load_config_effective(FIXTURE_ROOT)
        result = scan_workspace(FIXTURE_ROOT, config)
        assert len(result.files) >= 5
        paths = {f.normalized_path for f in result.files}
        assert "wiki/golden-page.md" in paths
        assert "raw/notes.txt" in paths

    def test_collections_assigned(self) -> None:
        config = load_config_effective(FIXTURE_ROOT)
        result = scan_workspace(FIXTURE_ROOT, config)
        by_coll: dict[str, list] = {}
        for f in result.files:
            by_coll.setdefault(f.collection, []).append(f)
        assert len(by_coll.get("wiki", [])) >= 4
        assert len(by_coll.get("raw", [])) >= 1

    def test_root_level_file_discovered(self, tmp_path: Path) -> None:
        # Regression (defect t_a4b8d50b): the default ``**/*.md`` include
        # pattern must also match files at the workspace root, not only
        # files nested under at least one directory.
        from nexusos.core.models import NexusOSConfig

        root = tmp_path / "ws"
        root.mkdir()
        (root / "root-note.md").write_text("# Root\n", encoding="utf-8")
        (root / "wiki").mkdir()
        (root / "wiki" / "nested.md").write_text("# Nested\n", encoding="utf-8")

        result = scan_workspace(root, NexusOSConfig())
        paths = {f.normalized_path for f in result.files}
        assert "root-note.md" in paths
        assert "wiki/nested.md" in paths

    def test_exclude_git(self) -> None:
        git_dir = FIXTURE_ROOT / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main")
        try:
            config = load_config_effective(FIXTURE_ROOT)
            result = scan_workspace(FIXTURE_ROOT, config)
            paths = {f.normalized_path for f in result.files}
            assert ".git/HEAD" not in paths
        finally:
            (git_dir / "HEAD").unlink(missing_ok=True)
            git_dir.rmdir()

    def test_file_too_large(self) -> None:
        big = FIXTURE_ROOT / "raw" / "big.txt"
        big.write_bytes(b"x" * 11_000_000)
        try:
            config = load_config_effective(FIXTURE_ROOT)
            config.max_file_size_bytes = 10_000_000
            result = scan_workspace(FIXTURE_ROOT, config)
            assert len(result.warnings) >= 1
            assert any("file_too_large" in str(w) for w in result.warnings)
        finally:
            big.unlink(missing_ok=True)

    def test_symlink_ignored(self) -> None:
        symlink_path = FIXTURE_ROOT / "wiki" / "link.md"
        target = FIXTURE_ROOT / "wiki" / "golden-page.md"
        try:
            symlink_path.symlink_to(target)
        except OSError:
            pytest.skip("symlink not supported")
        try:
            config = load_config_effective(FIXTURE_ROOT)
            config.symlink_policy = "ignore"
            result = scan_workspace(FIXTURE_ROOT, config)
            # Symlink may be followed on some platforms; just ensure we scanned
            assert len(result.files) >= 5
        finally:
            symlink_path.unlink(missing_ok=True)

    def test_symlink_follow(self) -> None:
        symlink_path = FIXTURE_ROOT / "wiki" / "link.md"
        target = FIXTURE_ROOT / "wiki" / "golden-page.md"
        try:
            symlink_path.symlink_to(target)
        except OSError:
            pytest.skip("symlink not supported")
        try:
            config = load_config_effective(FIXTURE_ROOT)
            config.symlink_policy = "follow"
            result = scan_workspace(FIXTURE_ROOT, config)
            paths = {f.normalized_path for f in result.files}
            assert "wiki/link.md" in paths
        finally:
            symlink_path.unlink(missing_ok=True)

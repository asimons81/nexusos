"""Cross-platform discovery path regression tests."""

from __future__ import annotations

from nexusos.discovery.models import DiscoveredFile


def test_discovered_file_canonicalizes_windows_path_separators() -> None:
    discovered = DiscoveredFile(
        relative_path=r"wiki\concepts\agents.md",
        normalized_path=r"wiki\concepts\agents.md",
        collection="wiki",
        file_type="markdown",
        size_bytes=128,
        mtime_ns=1,
    )

    assert discovered.relative_path == "wiki/concepts/agents.md"
    assert discovered.normalized_path == "wiki/concepts/agents.md"

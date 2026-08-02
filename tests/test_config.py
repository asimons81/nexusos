"""Tests for strict config validation."""

from __future__ import annotations

import pytest

from nexusos.core.config import _flatten_toml
from nexusos.core.errors import ConfigError


class TestFlattenToml:
    def test_unknown_section_raises(self) -> None:
        data = {"core": {"name": "test"}, "bogus_section": {"x": 1}}
        with pytest.raises(ConfigError, match="Unknown configuration section"):
            _flatten_toml(data)

    def test_unknown_key_raises(self) -> None:
        data = {"core": {"name": "test", "bogus_key": 42}}
        with pytest.raises(ConfigError, match="Unknown configuration section"):
            _flatten_toml(data)

    def test_valid_sections_pass(self) -> None:
        data = {
            "workspace": {"name": "test"},
            "files": {"include": ["*.md"], "exclude": []},
            "limits": {"max_file_size_bytes": 1000, "symlink_policy": "ignore"},
            "collections": {"wiki": "wiki"},
            "search": {"max_results": 50, "snippet_length": 200},
            "server": {"host": "0.0.0.0", "port": 1234},
            "lint": {"max_file_size_bytes": 5000, "warn_empty_docs": True},
            "indexing": {
                "chunk_max_chars": 1200,
                "chunk_overlap_chars": 100,
                "default_collection": "wiki",
            },
        }
        result = _flatten_toml(data)
        assert result["chunk_max_chars"] == 1200
        assert result["max_file_size_bytes"] == 1000

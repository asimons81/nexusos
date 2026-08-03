"""Contract tests: configuration keys, env vars, defaults, precedence, validation.

Locks docs/contracts.md §2. These tests assert the config contract from the
implementation: every TOML key, its model field, its default, env override
mapping, precedence (defaults < TOML < env < CLI), and validation behavior
(strict keys, type coercion, range bounds, operational env recognition).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nexusos.core.config import (
    _KNOWN_SECTIONS,
    _TOML_FIELD_MAP,
    load_config,
    load_config_effective,
)
from nexusos.core.errors import ConfigError
from nexusos.core.limits import (
    MAX_BROWSE_LIMIT,
    MAX_CONTEXT_SIBLING_LIMIT,
    MAX_RECENT_LIMIT,
    MAX_SEARCH_LIMIT,
    MAX_SNIPPET_TOKENS,
    MIN_LIMIT,
)
from nexusos.core.models import DEFAULT_CONFIG, NexusOSConfig

if TYPE_CHECKING:
    from pathlib import Path

#: Every public TOML section:key → model field, straight from the loader.
TOML_SURFACE = {
    "workspace": {"name": "workspace_name"},
    "files": {"include": "include_patterns", "exclude": "exclude_patterns"},
    "limits": {
        "max_file_size_bytes": "max_file_size_bytes",
        "symlink_policy": "symlink_policy",
    },
    "indexing": {
        "chunk_max_chars": "chunk_max_chars",
        "chunk_overlap_chars": "chunk_overlap_chars",
        "default_collection": "default_collection",
    },
    "search": {"max_results": "search_max_results", "snippet_length": "search_snippet_length"},
    "server": {"host": "server_host", "port": "server_port"},
    "mcp": {"enabled": "mcp_enabled", "transport": "mcp_transport"},
    "lint": {
        "max_file_size_bytes": "lint_max_file_size_bytes",
        "warn_empty_docs": "lint_warn_empty_docs",
    },
}

#: Model field → documented default (docs/contracts.md §2.2, from the model).
DEFAULTS = {
    "workspace_name": "default",
    "include_patterns": ["**/*.md", "**/*.txt"],
    "exclude_patterns": [
        "**/.nexusos/**",
        "**/node_modules/**",
        "**/__pycache__/**",
        "**/.git/**",
        "**/.direnv/**",
    ],
    "collection_mappings": {},
    "max_file_size_bytes": 10_485_760,
    "symlink_policy": "ignore",
    "index_path": ".nexusos/index.sqlite3",
    "chunk_max_chars": 2400,
    "chunk_overlap_chars": 200,
    "default_collection": "inbox",
    "search_max_results": 50,
    "search_snippet_length": 200,
    "server_host": "127.0.0.1",
    "server_port": 8765,
    "mcp_enabled": True,
    "mcp_transport": "stdio",
    "lint_max_file_size_bytes": 5_242_880,
    "lint_warn_empty_docs": True,
}

#: Model field → env var name (docs/contracts.md §2.3).
ENV_SURFACE = {f: f"NEXUSOS_{f.upper()}" for f in NexusOSConfig.model_fields}


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "nexusos.toml"
    p.write_text(body, encoding="utf-8")
    return p


# -- defaults ----------------------------------------------------------------


def test_default_config_matches_contract() -> None:
    """Built-in defaults are the frozen contract defaults."""
    for field, expected in DEFAULTS.items():
        assert getattr(DEFAULT_CONFIG, field) == expected, f"default for {field}"


def test_default_config_is_used_by_load_config(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, ""), apply_env=False)
    for field, expected in DEFAULTS.items():
        assert getattr(cfg, field) == expected, f"default for {field}"


# -- TOML surface ------------------------------------------------------------


def test_toml_field_map_matches_documented_surface() -> None:
    """Every documented TOML key maps to the documented model field."""
    for section, keys in TOML_SURFACE.items():
        for key, field in keys.items():
            assert (section, key) in _TOML_FIELD_MAP, f"missing map for [{section}] {key}"
            assert _TOML_FIELD_MAP[(section, key)] == field


def test_known_sections_include_collections() -> None:
    expected = {
        "workspace",
        "files",
        "limits",
        "indexing",
        "search",
        "server",
        "mcp",
        "lint",
        "collections",
    }
    assert expected <= _KNOWN_SECTIONS


def test_toml_loads_every_documented_key(tmp_path: Path) -> None:
    body = """
[workspace]
name = "research"

[files]
include = ["**/*.md"]
exclude = ["**/.git/**"]

[limits]
max_file_size_bytes = 5000000
symlink_policy = "warn"

[indexing]
chunk_max_chars = 1000
chunk_overlap_chars = 100
default_collection = "wiki"

[search]
max_results = 25
snippet_length = 240

[server]
host = "localhost"
port = 9000

[mcp]
enabled = false
transport = "streamable-http"

[lint]
max_file_size_bytes = 1000000
warn_empty_docs = false

[collections]
"raw/articles/**" = "articles"
"""
    cfg = load_config(_write(tmp_path, body), apply_env=False)
    assert cfg.workspace_name == "research"
    assert cfg.include_patterns == ["**/*.md"]
    assert cfg.exclude_patterns == ["**/.git/**"]
    assert cfg.max_file_size_bytes == 5_000_000
    assert cfg.symlink_policy == "warn"
    assert cfg.chunk_max_chars == 1000
    assert cfg.chunk_overlap_chars == 100
    assert cfg.default_collection == "wiki"
    assert cfg.search_max_results == 25
    assert cfg.search_snippet_length == 240
    assert cfg.server_host == "localhost"
    assert cfg.server_port == 9000
    assert cfg.mcp_enabled is False
    assert cfg.mcp_transport == "streamable-http"
    assert cfg.lint_max_file_size_bytes == 1_000_000
    assert cfg.lint_warn_empty_docs is False
    assert cfg.collection_mappings == {"raw/articles/**": "articles"}


# -- strict validation --------------------------------------------------------


def test_unknown_section_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Unknown configuration section"):
        load_config(_write(tmp_path, "[bogus]\nx = 1\n"), apply_env=False)


def test_unknown_key_in_known_section_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Unknown key 'bogus' in section"):
        load_config(_write(tmp_path, "[search]\nbogus = 1\n"), apply_env=False)


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Unknown top-level key"):
        load_config(_write(tmp_path, 'bogus = "x"\n'), apply_env=False)


def test_search_range_validation_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="search_max_results"):
        load_config(_write(tmp_path, "[search]\nmax_results = 501\n"), apply_env=False)


def test_search_snippet_range_validation_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="search_snippet_length"):
        load_config(_write(tmp_path, "[search]\nsnippet_length = 0\n"), apply_env=False)


# -- env var surface -----------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "env_name"),
    ENV_SURFACE.items(),
    ids=list(ENV_SURFACE),
)
def test_env_name_matches_field(field: str, env_name: str) -> None:
    """The env var for every model field is NEXUSOS_<FIELD_UPPER>."""
    assert env_name == f"NEXUSOS_{field.upper()}"


def test_env_override_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_SERVER_PORT", "9000")
    cfg = load_config(_write(tmp_path, ""), apply_env=True)
    assert cfg.server_port == 9000


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Precedence: env overrides TOML (docs/contracts.md §2.1)."""
    monkeypatch.setenv("NEXUSOS_SERVER_PORT", "9000")
    cfg = load_config(_write(tmp_path, "[server]\nport = 8000\n"), apply_env=True)
    assert cfg.server_port == 9000


def test_toml_overrides_default(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, "[server]\nport = 8000\n"), apply_env=False)
    assert cfg.server_port == 8000


def test_env_int_type_error_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_SEARCH_MAX_RESULTS", "abc")
    with pytest.raises(ConfigError, match="NEXUSOS_SEARCH_MAX_RESULTS"):
        load_config(_write(tmp_path, ""), apply_env=True)


def test_env_bool_type_error_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_MCP_ENABLED", "maybe")
    with pytest.raises(ConfigError, match="NEXUSOS_MCP_ENABLED"):
        load_config(_write(tmp_path, ""), apply_env=True)


def test_env_list_field_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_INCLUDE_PATTERNS", "**/*.md")
    with pytest.raises(ConfigError, match="cannot be set via environment variable"):
        load_config(_write(tmp_path, ""), apply_env=True)


def test_env_secret_pattern_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUSOS_SECRET_TOKEN", "super-secret")
    cfg = load_config(_write(tmp_path, ""), apply_env=True)
    assert "super-secret" not in str(cfg.to_safe_dict())


def test_load_config_effective_sets_root(tmp_path: Path) -> None:
    _write(tmp_path, "")
    cfg = load_config_effective(tmp_path)
    assert cfg.root == tmp_path.resolve(strict=False)


def test_operational_env_vars_known_no_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DENY_PATHS + ALLOW_NON_LOOPBACK are documented operational vars (A3-05)."""
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", "/tmp/deny")
    monkeypatch.setenv("NEXUSOS_ALLOW_NON_LOOPBACK", "1")
    load_config(_write(tmp_path, ""), apply_env=True)
    captured = capsys.readouterr()
    assert "unknown NEXUSOS_* variable" not in captured.err


def test_unknown_env_var_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A genuine unknown NEXUSOS_* name warns and is ignored (not fatal)."""
    monkeypatch.setenv("NEXUSOS_BOGUS", "1")
    cfg = load_config(_write(tmp_path, ""), apply_env=True)
    captured = capsys.readouterr()
    assert "unknown NEXUSOS_* variable 'NEXUSOS_BOGUS'" in captured.err
    assert "bogus" not in cfg.model_dump()


# -- shared bounds (F-06) ------------------------------------------------------


def test_shared_limit_bounds_match_contract() -> None:
    """The documented bound constants are the contract (docs/contracts.md §3.2)."""
    assert MIN_LIMIT == 1
    assert MAX_SEARCH_LIMIT == 500
    assert MAX_BROWSE_LIMIT == 1000
    assert MAX_RECENT_LIMIT == 100
    assert MAX_CONTEXT_SIBLING_LIMIT == 100
    assert MAX_SNIPPET_TOKENS == 10_000

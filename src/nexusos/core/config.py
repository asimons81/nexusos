"""Configuration loader: TOML file + env-var overrides."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path  # noqa: TC003
from typing import Any

from nexusos.core.errors import ConfigError
from nexusos.core.models import DEFAULT_CONFIG, NexusOSConfig

# Map TOML [section].key → model field name
_TOML_FIELD_MAP: dict[tuple[str, str], str] = {
    ("workspace", "name"): "workspace_name",
    ("files", "include"): "include_patterns",
    ("files", "exclude"): "exclude_patterns",
    ("limits", "max_file_size_bytes"): "max_file_size_bytes",
    ("limits", "symlink_policy"): "symlink_policy",
    ("indexing", "chunk_max_chars"): "chunk_max_chars",
    ("indexing", "chunk_overlap_chars"): "chunk_overlap_chars",
    ("indexing", "default_collection"): "default_collection",
    ("search", "max_results"): "search_max_results",
    ("search", "snippet_length"): "search_snippet_length",
    ("server", "host"): "server_host",
    ("server", "port"): "server_port",
    ("mcp", "enabled"): "mcp_enabled",
    ("mcp", "transport"): "mcp_transport",
    ("lint", "max_file_size_bytes"): "lint_max_file_size_bytes",
    ("lint", "warn_empty_docs"): "lint_warn_empty_docs",
}

# Recognised TOML sections and their known keys.
_KNOWN_SECTIONS: frozenset[str] = frozenset(s for s, _ in _TOML_FIELD_MAP) | {"collections"}

# Known NEXUSOS_* env var names (derived from model fields).
_KNOWN_ENV_NAMES: frozenset[str] = frozenset(
    f"NEXUSOS_{f.upper()}" for f in NexusOSConfig.model_fields
)

# Build the known-keys lookup for strict-key validation (collections is open).
_KNOWN_KEYS_BY_SECTION: dict[str, frozenset[str]] = {}
for _section in _KNOWN_SECTIONS:
    if _section == "collections":
        continue
    _KNOWN_KEYS_BY_SECTION[_section] = frozenset(
        k for (sec, k), _ in _TOML_FIELD_MAP.items() if sec == _section
    )


def load_toml(path: Path) -> dict[str, Any]:
    """Load and parse a nexusos.toml file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"Configuration file not found: {path}", exit_code=2)
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration file {path}: {exc}", exit_code=2)

    try:
        return tomllib.loads(raw)
    except Exception as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}", exit_code=2)


def _flatten_toml(toml_data: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested TOML sections into flat model field names.

    Validates that every top-level section and every key inside recognised
    sections is known. Unknown sections and misspelled keys produce a clear
    :class:`ConfigError` identifying the exact section/key.
    """
    result: dict[str, Any] = {}

    # Validate: every top-level section must be known or a model field.
    for section in toml_data:
        if not isinstance(toml_data[section], dict):
            # Leaf values at top level → check if they're model fields.
            if section not in NexusOSConfig.model_fields:
                raise ConfigError(
                    f"Unknown top-level key '{section}' in configuration; "
                    f"expected a section like [workspace], [files], [limits], "
                    f"[collections], [search], [server], or [lint]",
                    exit_code=2,
                )
            continue
        if section not in _KNOWN_SECTIONS and section not in NexusOSConfig.model_fields:
            raise ConfigError(
                f"Unknown configuration section [{section}]; "
                f"recognised sections: [{', '.join(sorted(_KNOWN_SECTIONS))}]",
                exit_code=2,
            )

    # Validate keys inside recognised sections.
    for section in _KNOWN_SECTIONS:
        if section not in toml_data:
            continue
        section_data = toml_data[section]
        if not isinstance(section_data, dict):
            continue
        known_keys = _KNOWN_KEYS_BY_SECTION.get(section)
        if known_keys is None:
            continue
        for key in section_data:
            if key not in known_keys:
                raise ConfigError(
                    f"Unknown key '{key}' in section [{section}]; "
                    f"recognised keys: [{', '.join(sorted(known_keys))}]",
                    exit_code=2,
                )

    # First, pass through any top-level keys that match model fields directly
    for key in NexusOSConfig.model_fields:
        if key in toml_data:
            result[key] = toml_data[key]

    # Map [section].key → field_name
    for (section, key), field in _TOML_FIELD_MAP.items():
        if section in toml_data and key in toml_data[section]:
            result[field] = toml_data[section][key]

    # [collections] maps to collection_mappings dict
    if "collections" in toml_data:
        result["collection_mappings"] = dict(toml_data["collections"])

    return result


def _env_override_map() -> dict[str, Any]:
    """Extract NEXUSOS_* env vars into a typed override dict.

    Unknown ``NEXUSOS_*`` configuration names produce a warning to stderr
    (the overrides are still applied — the warning is advisory so deployments
    do not break on a single stray env var).
    """
    overrides: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith("NEXUSOS_"):
            continue
        if any(marker in key.upper() for marker in ("SECRET", "TOKEN", "KEY", "PASSWORD")):
            continue
        config_key = key[len("NEXUSOS_") :].lower()
        if config_key not in NexusOSConfig.model_fields:
            print(
                f"nexusos: warning: unknown NEXUSOS_* variable '{key}' — ignored",
                file=sys.stderr,
            )
            continue
        if value.isdigit():
            overrides[config_key] = int(value)
        elif value.lower() in ("true", "false"):
            overrides[config_key] = value.lower() == "true"
        else:
            overrides[config_key] = value
    return overrides


def load_config(config_path: Path, *, apply_env: bool = True) -> NexusOSConfig:
    """Load the full configuration from a nexusos.toml path."""
    toml_data = load_toml(config_path)
    flat = _flatten_toml(toml_data)

    merged = DEFAULT_CONFIG.model_copy(deep=True)
    for key in NexusOSConfig.model_fields:
        if key in flat:
            setattr(merged, key, flat[key])

    if apply_env:
        env_overrides = _env_override_map()
        for key, value in env_overrides.items():
            if key in NexusOSConfig.model_fields:
                setattr(merged, key, value)

    return merged


def load_config_effective(workspace_root: Path) -> NexusOSConfig:
    """Load the effective config from a workspace root."""
    config_path = workspace_root / "nexusos.toml"
    config = load_config(config_path, apply_env=True)
    config.root = workspace_root.resolve(strict=False)
    return config


def config_to_safe_dict(config: NexusOSConfig) -> dict[str, Any]:
    """Export config to a display-safe dict (no secrets)."""
    return config.to_safe_dict()

"""Unit tests for configuration loader."""

from pathlib import Path

import pytest

from nexusos.core.config import load_config, load_toml
from nexusos.core.errors import ConfigError


def test_load_valid_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text("""
workspace_name = "test"
max_file_size_bytes = 1000
""")
    data = load_toml(config_path)
    assert data["workspace_name"] == "test"


def test_load_missing_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_toml(tmp_path / "nonexistent.toml")


def test_load_invalid_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text("not valid {{{")
    with pytest.raises(ConfigError):
        load_toml(config_path)


def test_load_config_falls_back_to_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text('workspace_name = "custom"\n')
    config = load_config(config_path, apply_env=False)
    assert config.workspace_name == "custom"
    assert config.server_port == 8765  # default


def test_load_config_effective(tmp_path: Path) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text('workspace_name = "effective_test"\n')
    config = load_config(config_path, apply_env=True)
    assert config.workspace_name == "effective_test"


def test_env_overrides_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text('workspace_name = "from_file"\nserver_port = 8000\n')
    monkeypatch.setenv("NEXUSOS_SERVER_PORT", "9000")
    config = load_config(config_path, apply_env=True)
    assert config.workspace_name == "from_file"  # TOML
    assert config.server_port == 9000  # env override


def test_env_overrides_secret_vars_not_exposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text('workspace_name = "test"\n')
    monkeypatch.setenv("NEXUSOS_SECRET_KEY", "should-not-appear")
    config = load_config(config_path, apply_env=True)
    safe = config.to_safe_dict()
    assert "should-not-appear" not in str(safe)
    assert "secret_key" not in safe  # skipped by _env_override_map

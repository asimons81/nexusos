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


def test_mcp_section_loads(tmp_path: Path) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text('[mcp]\nenabled = false\ntransport = "stdio"\n')
    config = load_config(config_path, apply_env=False)
    assert config.mcp_enabled is False
    assert config.mcp_transport == "stdio"


def test_mcp_defaults() -> None:
    from nexusos.core.models import DEFAULT_CONFIG

    assert DEFAULT_CONFIG.mcp_enabled is True
    assert DEFAULT_CONFIG.mcp_transport == "stdio"


def test_mcp_unknown_key_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text("[mcp]\nbogus = 1\n")
    with pytest.raises(ConfigError):
        load_config(config_path, apply_env=False)


def test_mcp_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text("")
    monkeypatch.setenv("NEXUSOS_MCP_ENABLED", "false")
    config = load_config(config_path, apply_env=True)
    assert config.mcp_enabled is False


def test_operational_env_vars_do_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Documented operational vars (DENY_PATHS, ALLOW_NON_LOOPBACK) must not
    trigger the 'unknown NEXUSOS_* variable' warning (A3-05 contract freeze).

    They are not configuration fields, but they are documented public env
    vars consumed by path safety and the serve policy, so the loader must
    treat them as known (skip silently) rather than as typos.
    """
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text("")
    monkeypatch.setenv("NEXUSOS_DENY_PATHS", "/tmp/deny")
    monkeypatch.setenv("NEXUSOS_ALLOW_NON_LOOPBACK", "1")
    config = load_config(config_path, apply_env=True)
    captured = capsys.readouterr()
    assert "unknown NEXUSOS_* variable" not in captured.err
    assert "deny_paths" not in config.model_dump()
    assert "allow_non_loopback" not in config.model_dump()


def test_unknown_env_var_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A genuine unknown NEXUSOS_* name still warns and is ignored (A3-05)."""
    config_path = tmp_path / "nexusos.toml"
    config_path.write_text("")
    monkeypatch.setenv("NEXUSOS_BOGUS", "1")
    config = load_config(config_path, apply_env=True)
    captured = capsys.readouterr()
    assert "unknown NEXUSOS_* variable 'NEXUSOS_BOGUS'" in captured.err
    assert "bogus" not in config.model_dump()

"""Unit tests for core models."""

import json

import pytest
from pydantic import ValidationError

from nexusos.core.models import (
    DEFAULT_CONFIG,
    CheckStatus,
    DoctorCheck,
    DoctorReport,
    WorkspaceIdentity,
)


def test_workspace_id_must_have_prefix() -> None:
    with pytest.raises(ValidationError):
        WorkspaceIdentity(workspace_id="bad_id", created_at="now", nexusos_version="1")


def test_workspace_id_valid() -> None:
    ws = WorkspaceIdentity(
        workspace_id="nxo_ws_abc123",
        created_at="2025-01-01T00:00:00Z",
        nexusos_version="0.1.0",
    )
    assert ws.workspace_id == "nxo_ws_abc123"
    assert ws.schema_version == 1


def test_workspace_id_rejects_empty_prefix() -> None:
    with pytest.raises(ValidationError):
        WorkspaceIdentity(workspace_id="nxo_ws_", created_at="now", nexusos_version="1")


def test_default_config() -> None:
    config = DEFAULT_CONFIG
    assert config.workspace_name == "default"
    assert config.max_file_size_bytes == 10_485_760
    assert config.server_port == 8765
    assert "**/*.md" in config.include_patterns


def test_config_merge() -> None:
    config = DEFAULT_CONFIG.model_copy(deep=True)
    merged = config.merge_overrides({"workspace_name": "custom"})
    assert merged.workspace_name == "custom"
    assert merged.server_port == 8765  # unchanged


def test_config_to_safe_dict() -> None:
    d = DEFAULT_CONFIG.to_safe_dict()
    assert isinstance(d, dict)
    assert d["workspace_name"] == "default"


def test_config_json_serializable() -> None:
    d = DEFAULT_CONFIG.to_safe_dict()
    json.dumps(d)  # should not raise


def test_doctor_check_status_constants() -> None:
    assert CheckStatus.PASS == "pass"
    assert CheckStatus.WARNING == "warning"
    assert CheckStatus.FAIL == "fail"


def test_doctor_check() -> None:
    c = DoctorCheck(check="test", status="pass", message="ok")
    assert c.check == "test"
    assert c.status == "pass"


def test_doctor_report() -> None:
    report = DoctorReport(
        checks=[DoctorCheck(check="a", status="pass", message="ok")],
        passed=1,
        healthy=True,
    )
    assert report.passed == 1
    assert report.healthy


def test_workspace_identity_immutable() -> None:
    ws = WorkspaceIdentity(
        workspace_id="nxo_ws_test1",
        created_at="now",
        nexusos_version="0.1.0",
    )
    with pytest.raises(Exception):
        ws.workspace_id = "nxo_ws_test2"  # type: ignore[misc]

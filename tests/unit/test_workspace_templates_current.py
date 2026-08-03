"""Regression tests for user-facing workspace templates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nexusos.workspace.init import init_workspace

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_starter_template_documents_current_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)
    workspace = tmp_path / "starter"

    init_workspace(workspace, template="starter")

    readme = (workspace / "README.md").read_text(encoding="utf-8")
    assert "nexusos doctor" in readme
    assert "nexusos index" in readme
    assert "nexusos search" in readme
    assert "nexusos mcp" in readme
    assert "future release" not in readme.lower()


def test_workspace_templates_include_current_configuration_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUSOS_DENY_PATHS", raising=False)

    for template in ("blank", "starter"):
        workspace = tmp_path / template
        init_workspace(workspace, template=template)
        config = (workspace / "nexusos.toml").read_text(encoding="utf-8")

        assert "[indexing]" in config
        assert "[search]" in config
        assert "[server]" in config
        assert "[mcp]" in config
        assert "[lint]" in config

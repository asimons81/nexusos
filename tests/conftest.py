"""Shared test fixtures for NexusOS tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_workspace() -> Path:
    """Create a temporary directory for workspace testing."""
    with tempfile.TemporaryDirectory(prefix="nxo_test_") as td:
        yield Path(td)


@pytest.fixture
def working_dir(temp_workspace: Path) -> Path:
    """Temporarily change to temp_workspace."""
    old = Path.cwd()
    os.chdir(str(temp_workspace))
    try:
        yield temp_workspace
    finally:
        os.chdir(str(old))


@pytest.fixture
def clean_env() -> dict[str, str]:
    """Environment without NEXUSOS_* vars."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("NEXUSOS_") and k not in ("PYTHONPATH",)
    }

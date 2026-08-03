"""Shared test fixtures for NexusOS tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_POSIX_PERMISSION_TESTS = {
    "test_database_regression_readonly_db_message",
    "test_database_regression_readonly_db_permission_error_type",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip chmod-enforcement tests on Windows.

    Windows does not implement POSIX directory write permissions through
    ``Path.chmod()``, so those tests cannot exercise the intended failure
    boundary there. Windows still runs the remaining database, indexing, and
    security suite.
    """
    del config
    if os.name != "nt":
        return

    marker = pytest.mark.skip(reason="requires POSIX chmod permission enforcement")
    for item in items:
        if item.name in _POSIX_PERMISSION_TESTS:
            item.add_marker(marker)


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

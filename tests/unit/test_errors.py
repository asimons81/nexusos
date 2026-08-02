"""Unit tests for core errors."""

from nexusos.core.errors import (
    ConfigError,
    DeniedPathError,
    DoctorError,
    NestedWorkspaceError,
    NexusOSError,
    NonEmptyDirectoryError,
    RootOrHomeError,
    SymlinkEscapeError,
    WorkspaceAlreadyExistsError,
    WorkspaceError,
    WorkspaceNotFoundError,
)


def test_base_error_exit_code() -> None:
    e = NexusOSError("test")
    assert e.exit_code == 1


def test_error_custom_exit_code() -> None:
    e = NexusOSError("test", exit_code=5)
    assert e.exit_code == 5


def test_denied_path_default_exit() -> None:
    e = DeniedPathError("blocked")
    assert e.exit_code == 2


def test_workspace_error_hierarchy() -> None:
    assert issubclass(WorkspaceError, NexusOSError)
    assert issubclass(WorkspaceNotFoundError, WorkspaceError)
    assert issubclass(DeniedPathError, WorkspaceError)
    assert issubclass(NestedWorkspaceError, WorkspaceError)
    assert issubclass(NonEmptyDirectoryError, WorkspaceError)
    assert issubclass(RootOrHomeError, WorkspaceError)
    assert issubclass(SymlinkEscapeError, WorkspaceError)
    assert issubclass(WorkspaceAlreadyExistsError, WorkspaceError)
    assert issubclass(ConfigError, NexusOSError)
    assert issubclass(DoctorError, NexusOSError)

"""Core error hierarchy for NexusOS."""


class NexusOSError(Exception):
    """Base error for all NexusOS exceptions."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ConfigError(NexusOSError):
    """Configuration parsing or validation error."""


class WorkspaceError(NexusOSError):
    """Workspace-related error (init, boundary, nesting)."""


class WorkspaceNotFoundError(WorkspaceError):
    """No workspace found at the given path."""


class WorkspaceAlreadyExistsError(WorkspaceError):
    """A workspace already exists at the target path."""


class NestedWorkspaceError(WorkspaceError):
    """Target is inside or contains another NexusOS workspace."""


class DeniedPathError(WorkspaceError):
    """Path is denied by NEXUSOS_DENY_PATHS."""

    def __init__(self, message: str, *, exit_code: int = 2) -> None:
        super().__init__(message, exit_code=exit_code)


class SymlinkEscapeError(WorkspaceError):
    """Symlink points outside the workspace boundary."""


class PathSafetyError(WorkspaceError):
    """Generic path-safety violation."""


class NonEmptyDirectoryError(WorkspaceError):
    """Directory is not empty and --adopt was not supplied."""


class RootOrHomeError(WorkspaceError):
    """Cannot initialize at filesystem root or home directory."""


class DoctorError(NexusOSError):
    """Doctor check failure that blocks operation."""


class TemplateError(NexusOSError):
    """Template loading or rendering error."""


# --- Indexing kernel errors (added in v0.1.0-alpha.2, additive only) ---


class IndexingError(NexusOSError):
    """Base error for the indexing kernel.

    Defaults to exit code 3 (runtime, database, migration, or indexing failure).
    """

    def __init__(self, message: str, *, exit_code: int = 3) -> None:
        super().__init__(message, exit_code=exit_code)


class DatabaseError(IndexingError):
    """Database initialization or operation failure."""


class DatabaseSchemaError(DatabaseError):
    """Database schema version is missing, incompatible, or unsupported."""


class CorruptDatabaseError(DatabaseError):
    """The index database is corrupt or not a valid SQLite database."""


class IndexTransactionError(IndexingError):
    """Index transaction could not be started, committed, or rolled back."""


class IndexEntryError(IndexingError):
    """Document-level index entry operation failure (defaults to exit code 1)."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message, exit_code=exit_code)


class IndexEntryExistsError(IndexEntryError):
    """An entry with the same identity already exists in the index."""


class IndexEntryNotFoundError(IndexEntryError):
    """The requested entry does not exist in the index."""


class WorkspaceMismatchError(IndexingError):
    """The index database is bound to a different workspace."""


class IndexLockError(IndexingError):
    """Index lock operation failure (defaults to exit code 5: lock conflict)."""

    def __init__(self, message: str, *, exit_code: int = 5) -> None:
        super().__init__(message, exit_code=exit_code)


class IndexLockConflictError(IndexLockError):
    """The index lock is held by another live process."""

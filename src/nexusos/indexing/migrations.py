"""Explicit, tested schema migrations for the NexusOS index database.

Migrations are versioned via ``PRAGMA user_version`` and applied stepwise.
Incompatible future schema versions are refused with a typed error.
"""

from __future__ import annotations

import sqlite3  # noqa: TC003

from nexusos.core.errors import DatabaseSchemaError
from nexusos.indexing.schema import (
    _MIGRATION_V2_WARNINGS,
    SCHEMA_STATEMENTS,
    SCHEMA_VERSION,
)


def current_schema_version(conn: sqlite3.Connection) -> int:
    """Read the schema version stored in ``PRAGMA user_version``."""
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    return int(row[0])


def migrate(conn: sqlite3.Connection, *, target: int = SCHEMA_VERSION) -> None:
    """Migrate the database to ``target`` (explicit, stepwise).

    Raises :class:`DatabaseSchemaError` when the database schema is newer than
    the supported version, or when no migration path exists.
    """
    current = current_schema_version(conn)
    if current == target:
        return
    if current > target:
        raise DatabaseSchemaError(
            f"database schema version {current} is newer than supported version {target}"
        )
    for version in range(current + 1, target + 1):
        _apply(conn, version)


def _apply(conn: sqlite3.Connection, version: int) -> None:
    """Apply the migration that produces schema ``version``, transactionally."""
    if version == 1:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.execute("PRAGMA user_version = 1")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    elif version == 2:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_MIGRATION_V2_WARNINGS)
            conn.execute("PRAGMA user_version = 2")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    else:
        raise DatabaseSchemaError(f"no migration path to schema version {version}")

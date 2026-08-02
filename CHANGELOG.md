# Changelog

## 0.1.0-alpha.2 (unreleased)

### Added

- Internal indexing kernel (`nexusos.indexing` package), the persistence foundation for Phase 2:
  - Deterministic, workspace-scoped identifiers (`nxo_doc_*`, `nxo_chk_*`, `nxo_run_*`) derived from the workspace ID and normalized relative path, stable across reindexing and content changes, and distinct between workspaces
  - Pydantic models for indexed documents, chunks, headings, wiki-links, run records, and row counts
  - SQLite schema v1 at `.nexusos/index.sqlite3` (configurable via `index_path`) with `meta`, `documents`, `headings`, `chunks`, an FTS5 preparation table (`chunks_fts`), `links`, and `index_runs` tables
  - Explicit, versioned schema migrations via `PRAGMA user_version`, refusing incompatible future versions with a typed error
  - Transactional persistence (single-writer `BEGIN IMMEDIATE`, nested-transaction rejection, WAL mode)
  - Exclusive-writer workspace index lock (`.nexusos/index.lock`) that reclaims stale locks owned by dead processes
  - `IndexKernel` API: `open`/`close`, `add_document`, `update_document`, `upsert_document`, `remove_document`, `get_document`, `lookup_candidates` (deterministic wiki-link candidate resolution), `counts`, `begin_run`/`complete_run`/`get_last_run`, `transaction`, `write_lock`, and `set_meta`/`get_meta`
  - Index-run records for status reporting, with per-run counters and success/error summaries
- Additive typed errors in `nexusos.core.errors`: `IndexingError` hierarchy (database, schema, corrupt database, transaction, entry, workspace-mismatch, lock) with dedicated exit codes
- 68 new unit tests for the indexing kernel (full suite: 148 passing)

### Not yet implemented

- File discovery and parsing pipeline (frontmatter, headings, chunking, wikilink extraction)
- `nexusos index` and `nexusos status` commands (the kernel is internal-only; no public CLI changes yet)
- Search, browse, read, recent, links, context commands
- MCP server (stdio and HTTP transports)
- Linting and staleness detection
- Embeddings or vector database
- Source mutation through MCP
- Cloud features, OAuth, multi-user

## 0.1.0-alpha.1 (unreleased)

### Added

- Project skeleton: `pyproject.toml`, `uv.lock`, `src/` layout
- Core error hierarchy (`NexusOSError` and typed subclasses)
- Configuration model (`NexusOSConfig`) with Pydantic v2 validation
- Path safety utilities: deny-list, symlink escape detection, nested workspace detection
- Workspace initialization with `blank` and `starter` templates
- Workspace identity generation with cryptographically secure random IDs
- `nexusos version` command
- `nexusos init` command with `--template`, `--dry-run`, `--adopt`
- `nexusos doctor` command with structured pass/warn/fail reports
- `nexusos config show` with `--effective` and `--json` output
- `NEXUSOS_DENY_PATHS` environment variable support with OS path separator
- `NEXUSOS_*` environment variable configuration overrides
- Atomic file writes for `.nexusos/workspace.json`
- Comprehensive unit tests for errors, models, path safety, init, config, doctor
- Security tests proving isolation boundaries
- CI workflow for Linux, macOS, Windows
- Apache-2.0 license

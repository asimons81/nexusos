# Changelog

## Unreleased

### Fixed

- **F-03 (P0)** — Path-safety TOCTOU in the indexer read path: a discovered
  file swapped for a symlink to an outside file between scan and read was
  ingested into the index. Reads now re-resolve the path against the
  workspace boundary immediately before opening (`read_source_text_safe`),
  refuse escaping symlinks, and open with `O_NOFOLLOW` where the platform
  supports it. Regression test proves the outside content is never indexed.
- **F-05 (P0)** — Relative `NEXUSOS_DENY_PATHS` entries resolved against the
  process CWD, making the deny list non-deterministic and silently missing
  intended targets. Relative entries are now ignored with a one-time warning;
  only absolute entries match. SECURITY.md documents absolute-only semantics.
- **F-06 (P0)** — Unbounded/negative result limits: `search --limit -1`
  returned every row (SQLite `LIMIT -1`), `browse --limit -1` truncated
  unexpectedly, and MCP accepted any limit. Search, browse, recent, context,
  MCP argument schemas, and `[search]` config values now validate against
  shared bounds (`[1, 500]` search results, `[1, 1000]` browse, `[1, 100]`
  recent/context, `[1, 10000]` snippet tokens) consistently across
  CLI/config/JSON/MCP.
- **F-07 (P0)** — `check_symlink_escape` was dead code in production paths.
  The defense is now live: `nexusos doctor` reports escaping symlinks as a
  warning check, and `nexusos init --adopt` refuses a tree whose symlinks
  resolve outside the workspace boundary.
- **F-08 (P0)** — Non-loopback bind policy for the unauthenticated MCP
  Streamable HTTP surface: the CLI and `python -m nexusos.mcp` now refuse a
  non-loopback bind (the endpoint is unauthenticated and includes the index
  write tool) unless the operator passes `--allow-non-loopback` or sets
  `NEXUSOS_ALLOW_NON_LOOPBACK=1`. The token-protected kernel-data HTTP
  transport keeps its warn-and-proceed behavior. Docs and SECURITY.md
  updated.
- Added 17 regression/adversarial tests covering every A3-01 finding
  (`tests/security/test_a3_01_release_fixes.py`); full suite: 435 passing.

### Changed

- Replaced the feature-bucket roadmap with an executable release train for
  `v0.1.0-alpha.3`, `v0.1.0-rc.1`, and stable, including scoped task IDs,
  dependencies, acceptance criteria, verification commands, and release gates.
- Reworked the README, contributor guide, agent instructions, architecture,
  configuration, MCP, linting, security, and release documentation around the current
  prerelease boundary and implemented behavior.
- Added structured roadmap issue and pull-request templates that require contract,
  acceptance, verification, security, and documentation evidence.
- Refreshed generated blank and starter workspace configuration and README content so new
  workspaces describe the current indexing, search, linting, serving, and MCP workflows.
- Normalized package metadata links to the canonical lowercase repository URL.

### Added

- Release procedure covering version consistency, artifact builds, clean installation,
  MCP validation, upgrade testing, publication, tagging, evidence, and rollback.
- Regression coverage that prevents generated workspace documentation and configuration
  from drifting behind implemented features.

## 0.1.0-alpha.2 (2026-08-02)

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
- Developer tooling commands:
  - `nexusos lint` — runs the project's own static-analysis tooling (ruff check, ruff format --check, mypy) over the kernel source and exits non-zero on findings; `--tool` selects a single tool, `--json` emits a machine-readable report
  - `nexusos serve` — read-only loopback HTTP server exposing kernel data (`/healthz`, `/api/status`, `/api/meta`, `/api/counts`, `/api/documents`, `/api/runs`) plus the bundled UI page; configurable `--host`/`--port` and clean SIGINT/SIGTERM shutdown
  - `nexusos demo` — scripted walkthrough of core features: creates a synthetic demo vault (init → seed → index → status → doctor) and prints usage examples; `--path` and `--remove` control the vault location/lifetime
- 20 smoke tests for the lint/serve/demo commands (registration, help, exit codes, HTTP endpoints, read-only guarantees, SIGINT shutdown)
- Content-navigation commands (`nexusos browse`, `read`, `recent`, `links`, `context`) backed by a shared read-only service layer, with `RecentDocument`/`IncomingLink` models and navigation error types
- `nexusos search <term>` — SQLite FTS5 full-text search over the indexed corpus: bm25-ranked results with source file path, line range, heading path, and highlight-marked excerpts; prefix matching and case-insensitive; safe query construction (`build_fts_query`) so FTS5 operators are treated as literal text; honors `[search] max_results` / `snippet_length` config with `--limit` override; `--json` emits the full report; read-only (never creates the index database)
- 46 unit + integration tests for search and content navigation (matched terms, no-match, multiple ranked results, prefix/case handling, limits, JSON output, exit codes, read-only invariant)
- MCP server (`nexusos mcp` / `python -m nexusos.mcp --workspace PATH`): Model Context Protocol over stdio exposing the workspace index as seven tools — `search`, `browse`, `read`, `recent`, `links`, `context`, and `index` (the indexer reuses the existing incremental index pass). Every tool advertises a strict schema (`additionalProperties: false`), returns JSON in both text and structured content, and surfaces service errors as MCP tool errors. `[mcp]` config section (`enabled`, `transport` — stdio only) with a client-connection example
- 31 unit + integration tests for the MCP server (tool registration, strict schemas, `[mcp]` config, real-subprocess stdio handshake, tool invocation returning valid JSON, missing-document errors, extra-argument rejection, indexing completion over a sample corpus, dry-run read-only guarantee)
- Workspace vault linter (`nexusos lint --workspace PATH`): read-only battery of checks over a vault's source files and index — broken wiki links, ambiguous links, invalid frontmatter, orphan documents, duplicate slugs, stale index, oversized files, empty documents, symlink escapes, and files outside configured collections. Runs a fresh discovery + parse pass so it works before indexing; warnings do not fail, failures exit 1. `[lint]` config section (`max_file_size_bytes`, `warn_empty_docs`); `--json` output. The plain `nexusos lint` (no `--workspace`) remains the kernel dev-tooling command
- MCP Streamable HTTP transport: `nexusos serve --transport streamable-http` serves MCP over loopback-only HTTP (default 127.0.0.1:8765, endpoint `/mcp`); `nexusos serve --transport stdio` runs the stdio MCP server; `[mcp] transport = "streamable-http"` is honored by `python -m nexusos.mcp`
- MCP `status` tool completing the Phase 5 tool list (workspace index status, counts, staleness reasons)
- 24 new unit/integration/security tests for the vault linter, lint CLI, serve transports, and MCP status tool (full suite: 355 passing)
- Documentation: docs/mcp.md, docs/linting.md; ROADMAP updated to mark alpha.2/3/4 complete

### Fixed

- **F1 (HIGH)** — O(n³) heading-path hang: indexing a Markdown file with thousands of headings froze `nexusos index` while holding the exclusive writer lock. Heading hierarchy now builds in a single-pass O(n) walk (shared by indexer, chunker, and parser); a 5,000-heading file indexes in under a second.
- **F2 (HIGH)** — Silent unreadable-directory skip: an unreadable source directory was silently skipped, so indexing could report success with zero files and zero warnings. Discovery now surfaces `unreadable_directory` warnings and `nexusos doctor` fails its `source_dirs_readable` check when one exists.
- **F-01 (MED)** — Temp-file symlink overwrite: atomic writes used a predictable temp path, allowing a pre-staged symlink to cause an arbitrary file write. Writes now use unpredictable `tempfile.mkstemp` names + `os.replace()`; `init --adopt` refuses a `.nexusos` that is a symlink, a regular file, or already seeded.
- **F-02 (MED)** — Host-header / DNS-rebinding exfiltration over the serve HTTP transport: non-loopback Host headers are rejected (403), all `/api/*` reads require a per-process `X-NexusOS-Token` (constant-time comparison), foreign Origins are rejected, and the bundled UI receives the token at serve time.
- **FD1 (MED)** — Stale-index detection missed content-only edits: `status`/`lint` now compare mtime/size signatures instead of path sets only.
- **FD2 (MED)** — Root-level files excluded by the default `**/*.md` include: globstar now matches zero-or-more directories, so root-level files (README.md, root notes) are discovered and indexed.
- **F3 (MED)** — Raw CLI tracebacks on `config show` / `init` / `serve`: errors now print clean `Error: ...` messages with correct exit codes (1/2) instead of Rich traceback panels.
- **F4 (MED)** — Read-only index database mislabeled as corrupt: read-only errors are detected as permission errors, read commands open with a mode=ro URI, and behind-schema DBs raise a clear "run `nexusos index`" message.
- **F5 (MED)** — `NEXUSOS_*` env override type validation: values are validated against model field annotations at load time; `ConfigError` names the offending variable.
- **F7 (MED)** — Discovery warnings counted but never surfaced: warning details (type/path/message) are persisted in `index_runs.warnings_json` (schema v2) and surfaced in human and JSON index output.
- 44 regression test functions added for the fixes above (full suite: 414 passing; ruff check/format and mypy clean).

### Not yet implemented

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

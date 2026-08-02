# Architecture

## Dependency Direction

```
core (errors, models, path_safety, config)
    ↓
workspace (init, identity)
    ↓
indexing (ids, models, schema, migrations, database, lock, kernel)
    ↓
services (doctor, index, status, search, navigation, lint)
    ↓
cli (Typer + Rich adapter)
mcp (MCP server over stdio)
```

- **core** — Zero UI dependencies. Pure Python types, validation, path logic.
- **workspace** — Templates, identity generation, boundary checks.
- **indexing** — Internal Phase 2 persistence kernel. Deterministic workspace-scoped IDs, SQLite schema + migrations, transactional storage, exclusive-writer lock, and the `IndexKernel` API (add/update/upsert/remove documents, deterministic candidate lookup, index-run records). Depends on core and workspace; no CLI or MCP imports.
- **services** — Reusable business logic, callable from CLI or MCP.
- **cli** — Thin adapter. Typer commands → service calls → output formatting.
- **mcp** — Top layer (sibling of `cli`). Wraps the service layer as MCP tools over stdio; never imports core internals or indexing directly. The CLI exposes it via `nexusos mcp` (lazy import) and `python -m nexusos.mcp` runs it directly.

## Design Principles

### Read-Only Contract

v0.1 never mutates source documents. The only allowed writes are:
- Files explicitly created by `nexusos init`
- Derived state inside `.nexusos/`
- Logs/reports explicitly requested

### Disposable Index

The index is fully rebuildable from source files. Delete `.nexusos/index.sqlite3` and re-run indexing — nothing is lost. The kernel enforces this: the database is derived state under `.nexusos/` and is never created by read-only commands (`doctor`, `status`).

### Local First

No network required. No proprietary formats. No accounts. No embeddings service.

### Deterministic Search

SQLite FTS5 only. Results are reproducible and source-cited. No LLM in the retrieval path.

## MCP Server

`nexusos mcp` (or `python -m nexusos.mcp --workspace PATH`) starts an MCP
server over stdio exposing the workspace index as tools: `search`, `browse`,
`read`, `recent`, `links`, `context`, and `index`. Every tool advertises a
strict schema (`additionalProperties: false`) and returns JSON-serializable
data in both text and structured content. Errors surface as MCP tool errors
(`isError: true`) instead of crashing the server.

## Not Yet Implemented

- Streamable HTTP / SSE transports for MCP (stdio is the only supported transport today)
- Linting and staleness detection for workspace vaults (the `lint` command runs the project's own dev tooling; a vault linter is a future product feature)
- Embeddings or vector database

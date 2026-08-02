# AGENTS.md

Implementation constraints for AI agents working on NexusOS.

## Isolation (non-negotiable)

- Work ONLY inside the NexusOS project directory
- Namespace: CLI `nexusos`, package `nexusos`, env `NEXUSOS_*`, state `.nexusos/`
- Never reference, import, or read private Nexus paths
- Tests must use synthetic fixtures only
- Never hardcode personal paths, names, domains

## Architecture

```
core (errors, models, path_safety, config)
    ↓
workspace (init)
    ↓
indexing (ids, models, schema, migrations, database, lock, kernel)
    ↓
services (doctor, index, status, search, navigation)
    ↓
cli (main) — Typer + Rich, NOT imported by core
mcp (server) — MCP over stdio, imports services only
```

Core must not import Typer, Rich, or MCP packages. Indexing must not import CLI or MCP packages. The `mcp` package is a top layer (sibling of `cli`): it imports `services` only, never `core` internals or `indexing` directly. The CLI may import `mcp` lazily to expose the `nexusos mcp` command.

## Code Style

- Python 3.11+, `from __future__ import annotations`
- `src/` layout, Pydantic v2, Typer, Rich
- Ruff for lint/format, mypy strict, pytest
- Max line length: 100
- Dependencies pinned via `uv.lock`

## Testing

- `uv run pytest -q` from project root
- No test references personal information
- Security tests must prove isolation boundaries
- Test paths and workspace IDs must be synthetic

## Current Phase

**Phase 0 + Phase 1 complete; Phase 2 kernel + CLI core done.** The internal `indexing/` kernel is implemented (deterministic workspace-scoped IDs, SQLite schema v1 with FTS5, explicit migrations, transactional persistence, exclusive-writer lock, `IndexKernel` API) and the CLI exposes `index`, `status`, `search`, `browse`, `read`, `recent`, `links`, `context`, `lint`, `serve`, `mcp`, and `demo`. Search is SQLite FTS5 only (bm25-ranked, prefix matching, line-aware excerpts, read-only). An MCP server (`nexusos mcp` / `python -m nexusos.mcp`, stdio transport) exposes search, browse, read, recent, links, context, and index as MCP tools with strict schemas; it reuses the read-only services for retrieval and the index service for corpus indexing. Embeddings, connectors, cloud, source mutation, and non-stdio transports are not yet implemented. Do not add placeholder commands that falsely claim these features work.

## Build Verification

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run nexusos version
```

All must pass before reporting completion.

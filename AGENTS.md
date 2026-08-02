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
services (doctor)
    ↓
cli (main) — Typer + Rich, NOT imported by core
```

Core must not import Typer, Rich, or MCP packages. Indexing must not import CLI or MCP packages.

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

**Phase 0 + Phase 1 complete; Phase 2 kernel core only.** The internal `indexing/` kernel is implemented (deterministic workspace-scoped IDs, SQLite schema v1 with FTS5 preparation rows, explicit migrations, transactional persistence, exclusive-writer lock, `IndexKernel` API). File discovery, parsing, chunking, the `index`/`status` commands, search, MCP, embeddings, connectors, cloud, and source mutation are not yet implemented. Do not add placeholder commands that falsely claim these features work.

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

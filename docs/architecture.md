# NexusOS Architecture

This document describes the implemented `v0.1.0-alpha.2` architecture and the contracts
that must remain stable through the v0.1 release train.

## System shape

```text
workspace source files
        │
        ▼
core + workspace boundaries
        │
        ▼
discovery, parsing, graph, chunking
        │
        ▼
transactional SQLite derived state
        │
        ▼
shared application services
        │
        ├── CLI adapter
        ├── MCP adapter
        └── local inspection API and UI
```

Source files are the authority. The SQLite index is derived state and must remain safe to
delete and rebuild.

## Dependency direction

```text
core (errors, models, path safety, configuration)
    ↓
workspace (initialization, identity, templates)
    ↓
indexing (discovery, parsing, graph, IDs, schema, migrations, database, lock, kernel)
    ↓
services (doctor, index, status, search, navigation, lint, serve, demo)
    ↓
cli (Typer and Rich adapter)

mcp (top-level adapter beside cli, importing services only)
```

### `core`

Pure domain types, errors, configuration loading, and path-safety logic.

Constraints:

- no Typer, Rich, MCP, CLI, or service imports
- no network requirement
- deterministic behavior for equivalent inputs

### `workspace`

Workspace initialization, identity, templates, and workspace-level boundaries.

Constraints:

- depends on `core`
- never imports CLI or MCP adapters
- writes only files explicitly created by initialization

### `indexing`

The persistence and retrieval kernel:

- file discovery
- Markdown and text parsing
- heading and wiki-link extraction
- deterministic chunking and identifiers
- graph resolution
- SQLite schema and migrations
- FTS5 search tables
- transactional persistence
- exclusive writer locking
- index-run records and warning details

Constraints:

- depends on `core` and `workspace`
- never imports CLI or MCP adapters
- treats the index as disposable state

### `services`

Reusable application behavior shared by interfaces. This layer owns workspace doctor,
indexing orchestration, status, search, navigation, vault linting, local serving, and demo
flows.

A behavior exposed through both CLI and MCP should be implemented here rather than copied
into both adapters.

### `cli`

The Typer and Rich adapter. It resolves user input, calls services, formats human or JSON
output, and maps typed failures to exit codes.

The CLI is not a business-logic layer.

### `mcp`

A top-level adapter beside `cli`. It exposes service contracts as MCP tools over stdio or
Streamable HTTP.

Constraints:

- imports services only
- never imports CLI code
- never reaches directly into database internals
- advertises strict schemas with `additionalProperties: false`
- converts typed service failures into MCP tool errors

## Data ownership

### Source state

User-owned Markdown and text files. NexusOS must not require conversion into a private
format and must not mutate source documents during v0.1 workflows.

### Derived state

Generated files under `.nexusos/`, including workspace identity, the SQLite index, lock
files, and index-run metadata.

Derived state may be replaced or deleted. Rebuilding it must not lose source data.

## Core invariants

### Source immutability

Indexing, search, browse, read, recent, links, context, status, doctor, linting, HTTP
inspection, and MCP retrieval must not edit source documents.

`index` may write derived state only.

### Deterministic identity

Document and chunk identifiers are workspace-scoped and derived from stable inputs.
Equivalent source paths in different workspaces must not collide.

### Transactional index updates

Index writes use transactional persistence and an exclusive writer lock. Readers must
never observe a partially committed index pass.

### Read-only commands do not create the database

Commands that inspect state must not create or migrate a missing database as a side
effect. A missing or behind-schema index should produce a clear instruction to run
`nexusos index`.

### Deterministic retrieval

Search uses SQLite FTS5 and returns source-aware results. No LLM or remote service sits in
the retrieval path.

### Explicit network boundary

Core workflows require no network. Local servers bind to loopback by default. A
non-loopback bind is an operator override and remains inside the known alpha security
boundary documented in [../SECURITY.md](../SECURITY.md).

## Interfaces

### CLI

The CLI exposes workspace lifecycle, indexing, search, navigation, linting, serving, and
demo commands. Current commands are summarized in [../README.md](../README.md); exact
options are defined by `nexusos COMMAND --help` and integration tests.

### MCP server

Launch over stdio:

```bash
nexusos mcp --workspace /path/to/workspace
```

Equivalent stdio form:

```bash
nexusos serve --transport stdio --workspace /path/to/workspace
```

Launch Streamable HTTP:

```bash
nexusos serve --transport streamable-http --workspace /path/to/workspace
```

The MCP tool set is `status`, `search`, `browse`, `read`, `recent`, `links`, `context`,
and `index`.

### Local inspection API and UI

`nexusos serve --workspace PATH` without an MCP transport starts the read-only local
inspection server and bundled UI. This is separate from the MCP Streamable HTTP endpoint,
even though both are reached through the `serve` command.

The inspection API exposes derived index information. `/api/*` requires the printed
per-process token, and the UI receives that token at serve time.

## Configuration flow

```text
built-in defaults
    ↓ overridden by
nexusos.toml
    ↓ overridden by
NEXUSOS_* environment variables
    ↓ overridden by
CLI flags where supported
```

Configuration is validated into `NexusOSConfig`. TOML sections and keys are strict except
for the open collection mapping. Environment variable names are based on model field
names, not TOML section paths.

See [configuration.md](configuration.md).

## Error flow

Domain and service failures use typed `NexusOSError` subclasses with intentional exit
codes. CLI adapters print clean error messages. MCP adapters return tool errors instead
of crashing the server.

Unexpected top-level CLI exceptions are caught by the console entry point and reduced to
a concise failure message rather than a raw traceback.

## Release architecture constraints

Until `v0.1.0` ships:

- no new storage backend
- no embeddings or vector database
- no source mutation tools
- no hosted authentication or synchronization layer
- no public contract change without tests and documentation
- no adapter-specific duplication of service behavior

Release work should harden, validate, package, and freeze this architecture rather than
expanding it. See [../ROADMAP.md](../ROADMAP.md).
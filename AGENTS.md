# AGENTS.md

This file defines the operating contract for AI coding agents working on NexusOS.
Read it before inspecting tasks, editing code, or changing documentation.

## Mission

NexusOS is a local-first knowledge operating system for AI agents. The v0.1 release
must provide a small, deterministic, well-tested memory contract over files the user
owns.

The repository is currently in **release hardening** for `v0.1.0-alpha.3`. The planned
core v0.1 feature scope shipped in `v0.1.0-alpha.2`. Do not add unrelated product scope
before stable release.

The executable release plan lives in [ROADMAP.md](ROADMAP.md).

## Isolation rules

These are non-negotiable:

- Work only inside the NexusOS project directory.
- Namespace all product state under CLI `nexusos`, package `nexusos`, environment
  variables `NEXUSOS_*`, and workspace state `.nexusos/`.
- Never reference, import, inspect, or depend on private Nexus projects or personal
  knowledge stores.
- Never hardcode personal names, paths, domains, credentials, or workspace content.
- Tests must use synthetic fixtures and temporary directories.
- Source documents are immutable unless a future, explicitly approved write system is
  implemented. v0.1 has no source-mutation feature.
- Derived state must remain disposable and rebuildable from source files.

## Architecture boundary

```text
core (errors, models, path safety, configuration)
    ↓
workspace (initialization, identity, templates)
    ↓
indexing (discovery, parsing, graph, schema, migrations, database, lock, kernel)
    ↓
services (doctor, index, status, search, navigation, lint, serve, demo)
    ↓
cli (Typer and Rich adapters)

mcp (top-level adapter beside cli, importing services only)
```

Rules:

- `core` must not import Typer, Rich, MCP, CLI, or service modules.
- `workspace` may depend on `core`, never on CLI or MCP.
- `indexing` may depend on `core` and `workspace`, never on CLI or MCP.
- `services` owns reusable application behavior.
- `cli` formats command input and output around services.
- `mcp` is a top layer. It imports services, not indexing internals or CLI code.
- CLI and MCP behavior should share service contracts rather than duplicate logic.

See [docs/architecture.md](docs/architecture.md) for the maintained architecture
reference.

## Current release boundary

Implemented in `v0.1.0-alpha.2`:

- workspace initialization, doctor, and configuration display
- path boundaries, deny paths, nested-workspace checks, and safe state writes
- Markdown and text discovery, parsing, deterministic chunking, and wiki-link graphing
- SQLite schema and migrations, FTS5, transactional persistence, and writer locking
- index, status, search, browse, read, recent, links, context, lint, serve, MCP, and demo
- MCP tools over stdio and Streamable HTTP
- read-only local inspection API and UI

Not in the v0.1 release scope:

- embeddings or vector databases
- web, PDF, or service ingestion connectors
- source mutation through CLI, HTTP, or MCP
- cloud hosting, OAuth, sync, teams, or multi-user authorization
- operational dashboards beyond the bundled local inspection UI

Do not create placeholder commands, empty interfaces, speculative configuration keys, or
documentation that implies these features work.

## Roadmap task protocol

Every release change must map to a task ID in [ROADMAP.md](ROADMAP.md), such as `A3-04`
or `RC-03`.

Before editing:

1. Read the roadmap task, dependencies, acceptance criteria, and verification gate.
2. Inspect the implementation and existing tests that define current behavior.
3. State the smallest coherent change required to complete the task.
4. Identify affected public contracts: CLI, configuration, JSON, MCP, docs, packaging,
   migrations, or exit codes.

During implementation:

1. Preserve dependency direction and source immutability.
2. Add or update tests for every behavior change and regression fix.
3. Keep the change scoped to one roadmap task unless dependencies make a combined
   change unavoidable.
4. Do not silently defer an acceptance criterion. Record the deferral and reason.
5. Update documentation and changelog entries in the same change when behavior or
   public contracts move.

Before reporting completion:

1. Run the required verification commands.
2. Confirm all task acceptance criteria with concrete evidence.
3. Report files changed, tests added, commands run, and any unresolved limitation.
4. Never report “done” based only on code generation or passing a narrow test subset.

## Coding standards

- Python 3.11+
- `from __future__ import annotations`
- `src/` package layout
- Pydantic v2 models
- Typer and Rich only in adapter layers
- Ruff for linting and formatting
- mypy strict mode
- pytest for unit, integration, regression, and security tests
- maximum line length: 100
- dependencies locked through `uv.lock`

Favor explicit typed models and narrow service interfaces. Avoid hidden global state,
implicit network access, non-deterministic retrieval behavior, and broad exception
swallowing.

## Testing contract

Use synthetic data only. Tests must not depend on personal files, network access, local
agent state, or machine-specific paths.

Behavior changes should be tested at the lowest useful level and at the public boundary
when appropriate:

- unit tests for pure logic and validation
- integration tests for service and CLI flows
- regression tests for reported defects
- security tests for filesystem boundaries, source immutability, server exposure, and
  unsafe input handling
- packaging smoke tests for installed artifacts during release work

Do not weaken an existing assertion merely to make a change pass. Explain and document
intentional contract changes.

## Required verification

The default repository gate is:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q --cov=nexusos
uv run nexusos version
```

The `--cov=nexusos` flag enforces the A3-03 aggregate coverage gate: `fail_under = 80`
in `[tool.coverage.report]` (measured baseline 84–85%, 2026-08-03). CI additionally
enforces targeted floors for security-critical modules (`core/path_safety.py`,
`indexing/lock.py`, `services/serve_service.py`, `mcp/`) and uploads the coverage
report as a per-leg artifact. Claims of "full test suite passing" must refer to the
measured suite and its measured coverage, never to an unmeasured literal 100%.

Roadmap tasks may require additional commands, platform matrices, clean-environment
installs, MCP client tests, package builds, or release checks. Run those in addition to
the default gate.

## Documentation contract

The following files describe public behavior and must remain aligned:

- `README.md`: user-facing overview, quick start, supported behavior, current status
- `ROADMAP.md`: release tasks, dependencies, acceptance criteria, and gates
- `CHANGELOG.md`: shipped and unreleased user-visible changes
- `SECURITY.md`: supported security boundary and vulnerability reporting
- `CONTRIBUTING.md`: contributor workflow and pull-request evidence
- `docs/architecture.md`: dependency direction and invariants
- `docs/configuration.md`: valid keys, environment variables, defaults, precedence
- `docs/mcp.md`: transports, tools, schemas, and safety boundary
- `docs/linting.md`: lint modes, checks, severities, and exit codes
- `docs/releasing.md`: build, validation, versioning, and publication procedure

When these files disagree with implementation, inspect the code and tests, correct the
contract deliberately, and update every affected document.

## Release language

Use precise terms:

- **core-scope complete:** planned v0.1 product capabilities are implemented
- **release hardening:** defects, contracts, packaging, platforms, docs, and security are
  being validated
- **release candidate:** intended stable artifact under real-world validation
- **stable:** published artifact and public contracts have passed all roadmap gates

Do not call an alpha “stable,” claim “full coverage” without a measured policy, or mark a
release complete because feature checkboxes are full.
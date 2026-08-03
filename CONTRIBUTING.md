# Contributing to NexusOS

NexusOS is in pre-release hardening for `v0.1.0`. Contributions should help complete a
roadmap task, fix a verified defect, strengthen tests, or bring documentation into line
with shipped behavior.

Read these first:

- [README.md](README.md)
- [ROADMAP.md](ROADMAP.md)
- [AGENTS.md](AGENTS.md)
- [docs/architecture.md](docs/architecture.md)
- [SECURITY.md](SECURITY.md)

## Development setup

Requirements:

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Git

```bash
git clone https://github.com/asimons81/nexusos.git
cd nexusos
uv sync
uv run nexusos version
```

Run the repository gate:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run nexusos version
```

## Pick a scoped task

Release work should reference a task ID from [ROADMAP.md](ROADMAP.md), such as `A3-02`
or `RC-04`.

Before opening a change:

1. confirm the task is not already being implemented
2. read its dependencies and acceptance criteria
3. inspect the current code and tests
4. keep the change limited to the smallest coherent contract

Do not add post-v0.1 product scope while the release train is in hardening unless the
roadmap is deliberately updated first.

## Project structure

```text
src/nexusos/
├── __init__.py       # Runtime version
├── core/             # Errors, models, path safety, configuration
├── workspace/        # Initialization, identity, templates
├── indexing/         # Discovery, parsing, graph, schema, database, kernel
├── services/         # Reusable application behavior
├── cli/              # Typer and Rich adapter
├── mcp/              # MCP adapter over services
└── ui/               # Bundled local inspection UI

tests/
├── unit/             # Pure logic and component behavior
├── integration/      # Service, CLI, MCP, and end-to-end behavior
├── security/         # Isolation and source-immutability proofs
└── fixtures/         # Synthetic test data
```

The maintained dependency rules are documented in
[docs/architecture.md](docs/architecture.md). `core`, `workspace`, and `indexing` must
never depend on CLI or MCP adapters.

## Coding standards

- Python 3.11+
- `from __future__ import annotations`
- complete type annotations under mypy strict mode
- Ruff for linting and formatting
- 100-character line limit
- Pydantic v2 models for validated data contracts
- reusable behavior in services, not duplicated in CLI and MCP layers
- no implicit network requirement in core workflows
- no source-document mutation in v0.1

## Tests

Use synthetic fixtures and temporary directories. Never use personal files, credentials,
private workspaces, or machine-specific paths.

Add the narrowest useful test first, then cover the public boundary when the change
alters user-visible behavior:

- unit tests for parsing, validation, models, and deterministic logic
- integration tests for CLI, service, indexing, HTTP, and MCP flows
- regression tests for fixed defects
- security tests for filesystem boundaries, server exposure, temporary files, and source
  immutability

A passing narrow test does not replace the full repository gate.

## Documentation changes

Documentation is part of the release contract. Update every affected surface in the same
change:

- command or option changes: README, CLI help, relevant docs, tests, changelog
- configuration changes: configuration docs, examples, validation tests, changelog
- MCP changes: MCP docs, schemas, integration tests, changelog
- security boundary changes: SECURITY, README, security tests, changelog
- release process changes: roadmap and releasing guide

Examples should be copied from verified behavior, not inferred from intended behavior.

## Pull request checklist

A pull request should include:

- the roadmap task or defect it addresses
- a concise statement of the public contract changed
- tests added or updated
- exact verification commands and results
- documentation changed
- remaining limitations or intentionally deferred work

Use this checklist in the PR body:

```markdown
## Scope

Roadmap task: A3-XX

## Contract

What user, agent, CLI, configuration, MCP, packaging, or security behavior changes?

## Evidence

- [ ] Ruff check passes
- [ ] Ruff format check passes
- [ ] mypy strict passes
- [ ] Full pytest suite passes
- [ ] Additional roadmap-specific verification passes
- [ ] Documentation is aligned
- [ ] Changelog is updated when user-visible behavior changed

## Limitations

List any accepted limitation or write `None`.
```

## Commit guidance

Prefer focused commits with imperative messages:

```text
fix: clamp search configuration values
ci: run integration suite on supported platforms
docs: align MCP transport contract
release: validate wheel installation flow
```

Avoid mixing formatting churn, unrelated refactors, and release behavior in the same
change.

## Security issues

Do not open a public issue for a suspected vulnerability. Follow the private reporting
instructions in [SECURITY.md](SECURITY.md).
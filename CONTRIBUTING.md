# Contributing

## Getting Started

```bash
git clone https://github.com/asimons81/nexusOS
cd nexusOS
uv sync
```

## Development

```bash
uv run ruff check .         # Lint
uv run ruff format --check . # Format check
uv run mypy src             # Type check
uv run pytest -q            # Tests
```

## Project Structure

```
src/nexusos/
├── __init__.py       # Version
├── core/             # Errors, models, path safety, config
├── workspace/        # Init, identity
├── indexing/         # Indexing kernel (ids, schema, migrations, database, lock, kernel)
├── services/         # Doctor
└── cli/              # Typer CLI adapter

tests/
├── unit/             # Unit tests
├── integration/      # Integration tests (future)
├── security/         # Isolation proofs
└── fixtures/         # Test fixtures
```

## Architecture

Core → Workspace → Services → CLI. Core never imports Typer or Rich.

## Coding Standards

- Python 3.11+
- Pydantic v2 models
- Type hints everywhere (mypy strict)
- Ruff for linting/formatting
- 100 char line limit
- `from __future__ import annotations`

# Development Guide

## Setup

```bash
git clone https://github.com/asimons81/nexusOS
cd nexusOS
uv sync
```

## Running Commands

```bash
uv run nexusos version
uv run nexusos init /tmp/test-ws
uv run nexusos doctor --workspace /tmp/test-ws
uv run nexusos config show --workspace /tmp/test-ws --effective
```

## Quality Checks

```bash
uv run ruff check .              # Linting
uv run ruff format --check .     # Format check
uv run ruff format .             # Auto-format
uv run mypy src                  # Type checking
uv run pytest -q                 # Tests
uv run pytest -q --cov=nexusos   # With coverage
```

## Running Specific Tests

```bash
uv run pytest tests/unit/test_init.py -v
uv run pytest tests/security/ -v
```

## Adding a Command

1. Add the service function in `src/nexusos/services/`
2. Core models in `src/nexusos/core/models.py` if needed
3. CLI command in `src/nexusos/cli/main.py`
4. Tests in `tests/unit/`

## Release Checklist

1. All tests pass on Linux, macOS, Windows (CI)
2. `CHANGELOG.md` updated
3. Version bumped in `pyproject.toml` and `src/nexusos/__init__.py`
4. Tag: `git tag v0.1.0-alpha.2`
5. Smoke test with `uv run nexusos init` + `doctor` on a clean path

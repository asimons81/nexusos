# NexusOS Linting

NexusOS exposes two lint modes through one command:

1. **workspace linting** for a user's knowledge workspace
2. **repository static analysis** for NexusOS contributors

The `--workspace` option selects workspace linting. Without it, `nexusos lint` runs the
repository development tools.

## Workspace linting

```bash
nexusos lint --workspace /path/to/workspace
nexusos lint --workspace /path/to/workspace --json
```

Workspace linting runs a fresh discovery and parse pass over source files. It can report
problems before the workspace has been indexed. The stale-index check separately reports
whether derived state is missing or out of date.

The linter is read-only. It must not create, migrate, or modify the index database and
must not edit source files.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | No failing checks; warnings may be present |
| `1` | One or more checks failed |
| `2` | Invalid input or workspace resolution failure |

### Checks

| Check | Severity | Detects |
|---|---|---|
| `broken-links` | fail | Wiki links with no matching document |
| `ambiguous-links` | fail | Wiki links matching multiple candidates |
| `unreadable-files` | fail | Source files that cannot be read or decoded as UTF-8 |
| `invalid-frontmatter` | fail | Frontmatter parse failures and invalid structure |
| `duplicate-slugs` | fail | Multiple documents sharing a filename stem |
| `stale-index` | fail | Missing or stale derived index state |
| `oversized-files` | fail | Files above the configured lint size limit |
| `orphans` | warn | Documents with no incoming wiki links |
| `empty-documents` | warn | Documents without body content |
| `symlink-escapes` | fail | Symlinks resolving outside the workspace boundary |
| `outside-collections` | warn | Files outside configured collection directories |

Warnings are findings, but warnings alone do not make the command exit `1`.

### Configuration

```toml
[lint]
max_file_size_bytes = 5242880
warn_empty_docs = true
```

Environment overrides use model field names:

```bash
export NEXUSOS_LINT_MAX_FILE_SIZE_BYTES=5242880
export NEXUSOS_LINT_WARN_EMPTY_DOCS=true
```

See [configuration.md](configuration.md) for validation and precedence.

### Link resolution

Workspace lint link checks mirror index graph resolution:

1. exact relative-path match
2. path plus supported suffix
3. unique filename-stem match
4. ambiguous when multiple candidates remain
5. broken when no candidate resolves

This keeps lint findings aligned with indexed link behavior.

### Unindexed workspaces

On an unindexed workspace:

- discovery and parsing checks still run
- link checks resolve against the discovered source set
- `stale-index` reports that the index is missing
- no index database is created as a side effect

### JSON output

`--json` returns the complete workspace lint report, including check status and findings.
Automation should evaluate the process exit code as well as the JSON body.

## Repository static analysis

Run from a NexusOS checkout:

```bash
nexusos lint
nexusos lint --tool ruff
nexusos lint --tool format
nexusos lint --tool mypy
nexusos lint --json
nexusos lint --repo /path/to/nexusos
```

Without `--workspace`, the command locates the repository and runs the configured static
analysis tools over the source tree.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Selected checks passed |
| `1` | A selected tool reported findings or failed to run |
| `2` | Invalid tool name or repository could not be resolved |

The repository lint command is convenient developer tooling. The complete release gate
still includes tests and a runtime smoke:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run nexusos version
```

## Agent guidance

Agents should use workspace lint findings as evidence, not as permission to edit source
files. A future guarded write workflow is outside the v0.1 release scope.

For repository work, do not report a roadmap task complete after running only
`nexusos lint`. Run the full task-specific verification required by
[../ROADMAP.md](../ROADMAP.md) and [../AGENTS.md](../AGENTS.md).
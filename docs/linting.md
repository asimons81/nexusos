# NexusOS Linting

NexusOS ships two kinds of linting. This page documents both, with an
emphasis on the workspace vault linter.

## Workspace vault linter

`nexusos lint --workspace PATH` runs a read-only battery of checks over a
vault's **source files and index**. It works whether or not the workspace
has been indexed yet — the stale-index check reports exactly that.

```bash
nexusos lint --workspace /path/to/workspace
nexusos lint --workspace /path/to/workspace --json
```

Exit codes:

- `0` — clean (no failed checks; warnings are allowed)
- `1` — one or more checks failed (findings detected)
- `2` — invalid input (e.g. missing workspace)

### Checks

| Check                    | Severity | Detects                                                     |
|--------------------------|----------|-------------------------------------------------------------|
| `broken-links`           | fail     | wiki links that resolve to no document                     |
| `ambiguous-links`        | fail     | wiki links matching more than one document stem            |
| `invalid-frontmatter`    | fail     | frontmatter parse warnings (bad YAML, missing `---`, dup keys) |
| `duplicate-slugs`        | fail     | two or more documents sharing a filename stem               |
| `stale-index`            | fail     | index missing, stale, or with source drift                 |
| `oversized-files`        | fail     | source files above the configured lint size cap            |
| `orphans`                | warn     | documents no other document links to                       |
| `empty-documents`        | warn     | documents with no body content                             |
| `symlink-escapes`        | fail     | symlinks resolving outside the workspace                   |
| `outside-collections`    | warn     | files not under any configured collection directory        |

Warnings do not fail the run; they surface in the report and in JSON.
Failures make `nexusos lint` exit 1.

### Configuration

The `[lint]` section in `nexusos.toml`:

```toml
[lint]
max_file_size_bytes = 5242880   # 5 MiB oversized-file cap
warn_empty_docs = true          # report empty documents as warnings
```

`NEXUSOS_LINT_MAX_FILE_SIZE_BYTES` / `NEXUSOS_LINT_WARN_EMPTY_DOCS`
override these.

### Design notes

- The linter is fully read-only: it never creates or mutates the index
  database. It runs a fresh discovery + parse pass so it works even before
  indexing.
- Link resolution mirrors `nexusos.indexing.graph` (exact path, then
  path+suffix, then unique filename stem; ambiguous on multiple matches),
  so findings agree with what the indexer would produce.
- `broken-links` on an **unindexed** workspace resolves against the
  discovered file set directly; the stale-index check separately reports
  that there is no index.

## Kernel static-analysis lint (developer tooling)

`nexusos lint` **without** `--workspace` runs the project's own tooling
(ruff, ruff format --check, mypy) over the NexusOS source tree. This is a
developer command for this repository, not a vault feature:

```bash
nexusos lint                     # ruff check + format + mypy
nexusos lint --tool mypy         # single tool
nexusos lint --json              # machine-readable report
nexusos lint --repo /path        # explicit repo root
```

Exit codes: `0` clean, `1` findings, `2` invalid input.

Both lint modes share the `--json` flag for machine-readable output.

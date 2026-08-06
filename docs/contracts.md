# NexusOS Public Contracts

> Status: frozen for `v0.1.0-rc.1` by roadmap task **A3-05** (unchanged from the alpha.3 freeze; RC-05 audit confirms the public surface is unchanged).
>
> This document is the inventory of the public interface users and agents can
> depend on. It is generated from the implementation and verified by the
> contract test suite in `tests/contracts/`. When implementation, tests, help
> text, README, or docs disagree, the implementation plus this inventory and
> the contract tests win — resolve drift deliberately across every affected
> document (AGENTS.md Documentation contract).

## Stability levels

| Level | Meaning |
|---|---|
| **Stable** | Frozen for v0.1. Covered by `tests/contracts/`. Changes require a deliberate roadmap decision and changelog entry. |
| **Operational** | Documented environment variables or CLI flags consumed outside the configuration model. Frozen names and semantics. |
| **Internal / unstable** | Implementation detail. Not presented as a stable public contract; may change without notice. |

---

## 1. CLI contract

### 1.1 Commands and options

Every command is registered in `nexusos --help` and covered by a contract
smoke test. Options use Typer conventions: `--option VALUE`, `-x` short
forms, `--flag` booleans, `--json` for machine-readable output.

| Command | Arguments | Options | Notes |
|---|---|---|---|
| `version` | — | — | Prints `nexusos <version>`. Exit 0. |
| `init` | `path` (required) | `--template/-t` (`starter` default, `blank`), `--dry-run`, `--adopt` | Creates a new workspace. `--adopt` allows a non-empty directory. |
| `doctor` | — | `--workspace/-w`, `--json` | Validates workspace health. Exit 0 healthy, 1 unhealthy. |
| `config` | `action` (default `show`) | `--workspace/-w`, `--effective/-e`, `--json` | Only `show` is supported. |
| `index` | — | `--workspace/-w`, `--full`, `--dry-run`, `--json` | Builds/increments the index. |
| `status` | — | `--workspace/-w`, `--json` | Reports index state and staleness. |
| `search` | `term` (required) | `--workspace/-w`, `--limit/-n`, `--json` | FTS5 search; limit default from config. |
| `lint` | — | `--tool` (`ruff`/`format`/`mypy`), `--json`, `--repo`, `--workspace/-w` | Two modes: kernel source lint (default) or workspace vault lint (`--workspace`). |
| `serve` | — | `--workspace/-w`, `--host`, `--port`, `--transport` (`http` default / `stdio` / `streamable-http`), `--allow-non-loopback` | Serves HTTP inspection API, MCP stdio, or MCP Streamable HTTP. |
| `mcp` | — | `--workspace/-w` | MCP stdio server (equivalent to `serve --transport stdio`). |
| `demo` | — | `--path`, `--remove` | Scripted synthetic walkthrough. |
| `browse` | `collection` (optional) | `--workspace/-w`, `--limit/-l`, `--json` | Lists indexed documents. |
| `read` | `item` (required) | `--workspace/-w`, `--lines/-n`, `--max-chars`, `--json` | Reads a document by ID, path, or name. |
| `recent` | — | `--workspace/-w`, `--limit/-l` (default 10), `--json` | Recently modified documents, newest first. |
| `links` | `item` (required) | `--workspace/-w`, `--json` | Outgoing + incoming wiki links. |
| `context` | `item` (required) | `--workspace/-w`, `--json` | Deterministic headings/siblings/linked evidence packet. |

Workspace resolution: explicit `--workspace PATH` wins; otherwise the nearest
workspace ancestor of the current directory (`.nexusos/workspace.json`) is
used. Commands that require a workspace exit 2 with
`Error: No workspace detected. Run \`nexusos init\` first.` when none is
found (verified: `status`, `index`, `search`, `browse`, `read`, `recent`,
`links`, `context`, `mcp`; `config show` exits 1 for the same condition).

### 1.2 Exit codes

| Code | Meaning | Verified surfaces |
|---|---|---|
| 0 | Success | All commands on success. |
| 1 | Generic/runtime failure, unhealthy result, unexpected error | `init` OSError, `doctor` unhealthy, `config` unknown action, `config` no workspace, `index` missing workspace path (stray error), `lint` findings, `read`/`links`/`context` missing document, `demo` unhealthy doctor, any uncaught exception (`nexusos: unexpected error: ...`). |
| 2 | Invalid input, safety-policy rejection, missing workspace, config error | `init` nested/existing/denied, `config` invalid TOML, `index`/`status`/`search`/etc. no workspace, `search` missing term (Typer), `--limit`/`--port` out of range, unknown `--transport`/`--tool`, non-loopback MCP bind refusal, MCP no workspace, `read`/etc. no index database. |
| 3 | Runtime/database/indexing failure, MCP disabled/unsupported | `index` run failure, `serve` MCP disabled, `serve` unsupported MCP transport, navigation/indexing database errors. |
| 5 | Index lock conflict | `IndexLockError` (another live process holds the writer lock). |

Documented invariants:

- `config show --effective` on invalid TOML exits 2 with a clean `Error:` line
  and no traceback (F3 regression locked by `test_cli_regression_*`).
- `serve --port 99999` exits 2 with a clean error (no `OverflowError`).
- Stray non-NexusOS exceptions degrade to `nexusos: unexpected error: ...`
  and exit 1, never a Rich traceback panel.
- `python -m nexusos.mcp` (argparse surface) uses exit 2 for no workspace and
  exit 3 for MCP-disabled/unsupported-transport, matching the CLI.

### 1.3 JSON output contract

Commands advertising `--json` emit a single JSON document on stdout (indent
2). Errors still use the `Error:` line on stderr; on error the JSON payload is
not emitted (except `doctor --json` which emits the report, then exits 1 when
unhealthy; `lint --json` which emits the report, then exits 1 on findings;
`index --json` which emits the run record, then exits 3 when unsuccessful).

| Command | Top-level keys (verified) |
|---|---|
| `doctor --json` | `checks`, `failures`, `healthy`, `passed`, `warnings`, `workspace_root` |
| `config show --json` / `--effective --json` | `chunk_max_chars`, `chunk_overlap_chars`, `collection_mappings`, `default_collection`, `exclude_patterns`, `include_patterns`, `index_path`, `lint_max_file_size_bytes`, `lint_warn_empty_docs`, `max_file_size_bytes`, `mcp_enabled`, `mcp_transport`, `root`, `search_max_results`, `search_snippet_length`, `server_host`, `server_port`, `symlink_policy`, `workspace_name` |
| `index --json` | `completed_at`, `documents_failed`, `error_count`, `error_summary`, `files_added`, `files_deleted`, `files_seen`, `files_unchanged`, `files_updated`, `mode`, `run_id`, `started_at`, `success`, `warning_count`, `warnings` |
| `status --json` | `ambiguous_link_count`, `chunk_count`, `config_schema_version`, `document_count`, `heading_count`, `index_schema_version`, `last_index_run_id`, `last_successful_index_at`, `read_only`, `resolved_link_count`, `server_version`, `stale`, `stale_reasons`, `status`, `unresolved_link_count`, `workspace_id` |
| `search --json` | `query`, `results`, `total` |
| `browse --json` | `collection`, `count`, `documents`, `workspace` |
| `recent --json` | `count`, `documents`, `limit`, `workspace` |
| `links --json` | `document_id`, `path`, `title`, `collection`, `outgoing`, `incoming` |
| `context --json` | `document_id`, `path`, `title`, `collection`, `headings`, `siblings`, `linked`, `outgoing`, `incoming` |
| `read --json` | `document_id`, `path`, `title`, `collection`, `content`, `truncated` |
| `lint --json` (vault) | `checks`, `failed`, `has_findings`, `passed`, `warned`, `workspace` |
| `lint --json` (kernel) | `repo_root`, `checks`, `passed`, `failed`, `errors`, `has_findings` |

`status --json` is always emitted (never errors for missing index) and reports
`status` in `uninitialized` / `ready` / `stale` / `error`, with
`read_only: true` always.

---

## 2. Configuration contract

### 2.1 Sources and precedence

Effective values resolve in this order (later layers override earlier ones):

1. built-in defaults (`nexusos.core.models.DEFAULT_CONFIG`)
2. `nexusos.toml` at the workspace root
3. `NEXUSOS_*` environment variables
4. CLI flags where a command exposes an override

`config show` displays file values merged over defaults **without** env
overrides; `config show --effective` includes recognized env overrides.

### 2.2 TOML keys and defaults

Configuration is strict: unknown sections and unknown keys inside recognized
sections fail with a `ConfigError` (exit 2) naming the exact key. The
`[collections]` table is an open mapping of path patterns to collection names.

| Section | Key | Model field | Default | Validation |
|---|---|---|---|---|
| `[workspace]` | `name` | `workspace_name` | `"default"` | string |
| `[files]` | `include` | `include_patterns` | `["**/*.md", "**/*.txt"]` | list of globs |
| `[files]` | `exclude` | `exclude_patterns` | `["**/.nexusos/**", "**/node_modules/**", "**/__pycache__/**", "**/.git/**", "**/.direnv/**"]` | list of globs |
| `[limits]` | `max_file_size_bytes` | `max_file_size_bytes` | `10485760` (10 MiB) | non-negative int |
| `[limits]` | `symlink_policy` | `symlink_policy` | `"ignore"` | `ignore` / `warn` / `deny` |
| `[indexing]` | `chunk_max_chars` | `chunk_max_chars` | `2400` | positive int |
| `[indexing]` | `chunk_overlap_chars` | `chunk_overlap_chars` | `200` | non-negative int |
| `[indexing]` | `default_collection` | `default_collection` | `"inbox"` | string |
| `[search]` | `max_results` | `search_max_results` | `50` | int in `[1, 500]` (F-06) |
| `[search]` | `snippet_length` | `search_snippet_length` | `200` | int in `[1, 10000]` (F-06) |
| `[server]` | `host` | `server_host` | `"127.0.0.1"` | string |
| `[server]` | `port` | `server_port` | `8765` | int in `[0, 65535]` |
| `[mcp]` | `enabled` | `mcp_enabled` | `true` | bool |
| `[mcp]` | `transport` | `mcp_transport` | `"stdio"` | `stdio` / `streamable-http` |
| `[lint]` | `max_file_size_bytes` | `lint_max_file_size_bytes` | `5242880` (5 MiB) | non-negative int |
| `[lint]` | `warn_empty_docs` | `lint_warn_empty_docs` | `true` | bool |
| `[collections]` | any pattern | `collection_mappings` | `{}` | pattern → collection string |

Top-level model fields (`workspace_name`, `max_file_size_bytes`, ...) are also
accepted directly in TOML as a compatibility surface.

### 2.3 Environment variables

Environment variable names are derived from the **model field name**, not the
TOML section path: `NEXUSOS_<FIELD_UPPER>`.

| Field | Env var |
|---|---|
| `workspace_name` | `NEXUSOS_WORKSPACE_NAME` |
| `include_patterns` | `NEXUSOS_INCLUDE_PATTERNS` (rejected: list field) |
| `exclude_patterns` | `NEXUSOS_EXCLUDE_PATTERNS` (rejected: list field) |
| `collection_mappings` | `NEXUSOS_COLLECTION_MAPPINGS` (rejected: dict field) |
| `max_file_size_bytes` | `NEXUSOS_MAX_FILE_SIZE_BYTES` |
| `symlink_policy` | `NEXUSOS_SYMLINK_POLICY` |
| `index_path` | `NEXUSOS_INDEX_PATH` (internal, see §2.5) |
| `chunk_max_chars` | `NEXUSOS_CHUNK_MAX_CHARS` |
| `chunk_overlap_chars` | `NEXUSOS_CHUNK_OVERLAP_CHARS` |
| `default_collection` | `NEXUSOS_DEFAULT_COLLECTION` |
| `search_max_results` | `NEXUSOS_SEARCH_MAX_RESULTS` |
| `search_snippet_length` | `NEXUSOS_SEARCH_SNIPPET_LENGTH` |
| `server_host` | `NEXUSOS_SERVER_HOST` |
| `server_port` | `NEXUSOS_SERVER_PORT` |
| `mcp_enabled` | `NEXUSOS_MCP_ENABLED` |
| `mcp_transport` | `NEXUSOS_MCP_TRANSPORT` |
| `lint_max_file_size_bytes` | `NEXUSOS_LINT_MAX_FILE_SIZE_BYTES` |
| `lint_warn_empty_docs` | `NEXUSOS_LINT_WARN_EMPTY_DOCS` |
| `root` | `NEXUSOS_ROOT` (internal, see §2.5) |

Environment override behavior (verified):

- ints are parsed as ints; a non-integer value raises `ConfigError` naming the
  variable (exit 2).
- booleans accept `true`/`false`/`1`/`0`; anything else raises `ConfigError`.
- list and dict fields cannot be set via env; a `ConfigError` explains the
  limitation.
- unknown `NEXUSOS_*` names print
  `nexusos: warning: unknown NEXUSOS_* variable '...' — ignored` to stderr and
  are ignored (not fatal).
- names containing `SECRET`, `TOKEN`, `KEY`, or `PASSWORD` are skipped by the
  loader and never displayed.

### 2.4 Operational environment variables

These are documented public env vars consumed outside the configuration model.
They are **not** config fields (never appear in `config show`), but the
loader treats them as known — no spurious "unknown NEXUSOS_* variable"
warning (A3-05 contract freeze).

| Env var | Semantics | Consumed by |
|---|---|---|
| `NEXUSOS_DENY_PATHS` | OS-path-separator list of absolute paths denied as workspace targets (F-05: relative entries are ignored with a one-time warning; entries must be absolute) | `init`, `doctor`, path safety |
| `NEXUSOS_ALLOW_NON_LOOPBACK` | Set to `1` to allow MCP Streamable HTTP to bind a non-loopback host (F-08) | `serve --transport streamable-http`, `python -m nexusos.mcp` |

### 2.5 Internal / unstable configuration fields

- `root` (`NEXUSOS_ROOT`): set by `load_config_effective` to the resolved
  workspace root; not a user-settable tuning knob.
- `index_path` (`NEXUSOS_INDEX_PATH`): present in the model for future use;
  the current indexer always writes `.nexusos/index.sqlite3`. Do not rely on
  it in v0.1.

---

## 3. MCP contract

### 3.1 Server identity

| Property | Value (verified) |
|---|---|
| name | `nexusos` |
| title | `NexusOS` |
| version | package version (e.g. `0.1.0-rc.1`) |
| instructions | descriptive text covering the tool set |

Transports: stdio (`nexusos mcp` / `nexusos serve --transport stdio` /
`python -m nexusos.mcp`) and Streamable HTTP (`nexusos serve --transport
streamable-http`, loopback-only default, endpoint `/mcp`).

### 3.2 Tools

The server registers exactly these eight tools (stable set, verified by
`test_build_server_registers_expected_tools`). Every tool advertises a strict
JSON schema with `additionalProperties: false`; unknown arguments are
rejected by the SDK.

| Tool | Input schema | Defaults / bounds | Writes |
|---|---|---|---|
| `status` | `{}` | — | No |
| `search` | `term` (required str), `limit` (int), `snippet_tokens` (int) | `limit=50` in `[1, 500]`; `snippet_tokens=200` in `[1, 10000]` | No |
| `browse` | `collection` (str\|null), `limit` (int\|null) | `limit` in `[1, 1000]` | No |
| `read` | `item` (required str), `max_lines` (int\|null), `max_chars` (int\|null) | — | No |
| `recent` | `limit` (int) | `limit=10` in `[1, 100]` | No |
| `links` | `item` (required str) | — | No |
| `context` | `item` (required str), `sibling_limit` (int) | `sibling_limit=50` in `[1, 100]` | No |
| `index` | `full` (bool), `dry_run` (bool) | `false` / `false` | Derived state only |

Shared bounds (F-06, `nexusos.core.limits`): `MIN_LIMIT=1`,
`MAX_SEARCH_LIMIT=500`, `MAX_BROWSE_LIMIT=1000`, `MAX_RECENT_LIMIT=100`,
`MAX_CONTEXT_SIBLING_LIMIT=100`, `MAX_SNIPPET_TOKENS=10000`. These same
bounds are enforced by CLI `--limit`, config `[search]`, and JSON paths.

### 3.3 Output and error behavior

- Tool results are JSON-serializable dicts matching the CLI JSON shapes for
  the same operation (`search` returns `{query, total, results}`; `browse`
  returns `{workspace, collection, count, documents}`; etc.).
- Service errors (`WorkspaceNotFoundError`, `IndexingError`,
  `DocumentNotFoundError`, `AmbiguousDocumentError`, range violations) surface
  as MCP tool errors carrying the service message — never a server crash.
- Read-only invariant: `status`, `search`, `browse`, `read`, `recent`,
  `links`, `context` never create a missing index database; `index` is the
  only tool that writes derived state (inside `.nexusos/`).
- `[mcp] enabled = false` refuses MCP startup for that workspace (CLI exit 3,
  `python -m nexusos.mcp` exit 3).
- F-08: Streamable HTTP refuses a non-loopback bind unless
  `--allow-non-loopback` / `NEXUSOS_ALLOW_NON_LOOPBACK=1` (CLI exit 2).

---

## 4. HTTP inspection API (`serve --transport http`)

The kernel-data HTTP server is a read-only inspection surface (token
protected). Endpoints (verified):

| Endpoint | Purpose | Auth |
|---|---|---|
| `/healthz` | liveness (`{"ok": true, "version": ...}`) | none |
| `/api/status` | same payload as `status --json` | `X-NexusOS-Token` |
| `/api/meta` | index metadata | `X-NexusOS-Token` |
| `/api/counts` | document/chunk/heading/link counts | `X-NexusOS-Token` |
| `/api/documents` | document list | `X-NexusOS-Token` |
| `/api/documents/<path>` | single document | `X-NexusOS-Token` |
| `/api/runs` | last index run record | `X-NexusOS-Token` |
| `/ui/*` | bundled UI assets | none |

Security invariants (F-02, F-08): Host header must name a loopback host (else
403); exactly one Host header required; foreign Origin rejected; every `/api/*`
read requires the per-process `X-NexusOS-Token` (constant-time compare); a
non-loopback bind warns and proceeds (token is the only access control). The
MCP Streamable HTTP endpoint and the inspection API are separate surfaces with
different contracts — do not document `/mcp` as an inspection route or vice
versa.

---

## 5. Unstable / internal behavior (NOT a stable contract)

The following are explicitly **not** part of the frozen v0.1 public contract
and may change without notice:

- `nexusos.config` internal model fields `root` and `index_path` (§2.5).
- The `nexusos lint` kernel-source mode (`--tool ruff|format|mypy`,
  `--repo`) — developer tooling, not a product feature.
- The `demo` command's exact printed walkthrough text.
- The exact human-readable (non-JSON) table layouts rendered by Rich.
- `nexusos serve` server banner text (the token line and URL line format).
- MCP server `instructions` prose.
- `nexusos.lint` / vault-linter per-check message wording (check names and
  JSON shape are stable; message strings are not).
- HTTP response body wording for 4xx error payloads (status codes and JSON
  structure are stable).

Anything not listed above as stable should be treated as internal until a
later release explicitly freezes it.

---

## 6. Contract test suite

`tests/contracts/` is the executable lock on this document. It covers:

- every CLI command and public option (help + smoke),
- exit codes for nontrivial failure modes,
- config keys, env vars, defaults, precedence, and validation,
- JSON output parseability and top-level shape for every `--json` command,
- MCP tool names, schemas, bounds, and error behavior,
- operational env var recognition (DENY_PATHS, ALLOW_NON_LOOPBACK),
- serve transport validation and non-loopback policy.

Run it with:

```bash
uv run pytest tests/contracts/ -q
```

CI runs the contract suite on every push/PR (see `.github/workflows/ci.yml`).

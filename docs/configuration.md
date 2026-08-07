# NexusOS Configuration

Each workspace uses a `nexusos.toml` file at its root. Configuration is strict: unknown
sections and misspelled keys fail with a clear error instead of being silently accepted.

## Precedence

Effective values are resolved in this order, with later layers overriding earlier ones:

1. built-in defaults
2. values from `nexusos.toml`
3. `NEXUSOS_*` environment variables
4. CLI flags where a command exposes an override

Not every setting has a CLI flag.

## Complete example

```toml
[workspace]
name = "my-knowledge-base"

[files]
include = ["**/*.md", "**/*.markdown", "**/*.txt"]
exclude = [
  "**/.nexusos/**",
  "**/node_modules/**",
  "**/__pycache__/**",
  "**/.git/**",
  "**/.direnv/**",
]

[limits]
max_file_size_bytes = 10485760
symlink_policy = "ignore"

[indexing]
chunk_max_chars = 2400
chunk_overlap_chars = 200
default_collection = "inbox"

[search]
max_results = 50
snippet_length = 200

[server]
host = "127.0.0.1"
port = 8765

[mcp]
enabled = true
transport = "stdio"

[lint]
max_file_size_bytes = 5242880
warn_empty_docs = true

[collections]
"raw/articles/**" = "articles"
"wiki/projects/**" = "projects"
```

## Sections and keys

### `[workspace]`

| Key | Default | Meaning |
|---|---:|---|
| `name` | `"default"` | Human-readable workspace name |

### `[files]`

| Key | Default | Meaning |
|---|---|---|
| `include` | Markdown and text glob patterns | Files eligible for discovery |
| `exclude` | Generated, VCS, dependency, and cache paths | Files excluded from discovery |

### `[limits]`

| Key | Default | Meaning |
|---|---:|---|
| `max_file_size_bytes` | `10485760` | Maximum file size accepted by indexing |
| `symlink_policy` | `"ignore"` | Symlink behavior: `ignore`, `warn`, or `deny` |

### `[indexing]`

| Key | Default | Meaning |
|---|---:|---|
| `chunk_max_chars` | `2400` | Maximum target chunk size in characters |
| `chunk_overlap_chars` | `200` | Character overlap between adjacent chunks |
| `default_collection` | `"inbox"` | Collection used when no mapping matches |

### `[search]`

| Key | Default | Meaning |
|---|---:|---|
| `max_results` | `50` | Default result limit (validated range `1..500`) |
| `snippet_length` | `200` | Search excerpt length passed to retrieval (validated range `1..10000`) |

`max_results` and `snippet_length` are validated against the same shared bounds as the
CLI/MCP surfaces (F-06 resolved); out-of-range values fail configuration load.

### `[server]`

| Key | Default | Meaning |
|---|---:|---|
| `host` | `"127.0.0.1"` | Bind host for local HTTP modes |
| `port` | `8765` | Bind port |

Loopback is the supported default. A non-loopback host is an explicit operator override;
review [../SECURITY.md](../SECURITY.md) before using one. MCP Streamable HTTP refuses a
non-loopback bind unless `--allow-non-loopback` or `NEXUSOS_ALLOW_NON_LOOPBACK=1` is set
(F-08 resolved).

### `[mcp]`

| Key | Default | Meaning |
|---|---:|---|
| `enabled` | `true` | Allow the MCP server to start for this workspace |
| `transport` | `"stdio"` | Default transport: `stdio` or `streamable-http` |

When `enabled = false`, MCP startup refuses the workspace and exits non-zero.

### `[lint]`

| Key | Default | Meaning |
|---|---:|---|
| `max_file_size_bytes` | `5242880` | Oversized-file threshold for workspace lint |
| `warn_empty_docs` | `true` | Report empty source documents as warnings |

### `[collections]`

The collections table is an open mapping of path patterns to collection names:

```toml
[collections]
"raw/articles/**" = "articles"
"wiki/concepts/**" = "concepts"
```

Unlike the other sections, collection keys are user-defined patterns.

## Environment variables

Environment variables use the **configuration model field name**, not the TOML section
and key path.

Examples:

```bash
export NEXUSOS_WORKSPACE_NAME="research"
export NEXUSOS_MAX_FILE_SIZE_BYTES=5000000
export NEXUSOS_SEARCH_MAX_RESULTS=25
export NEXUSOS_SEARCH_SNIPPET_LENGTH=240
export NEXUSOS_SERVER_PORT=9000
export NEXUSOS_MCP_ENABLED=true
export NEXUSOS_MCP_TRANSPORT=stdio
export NEXUSOS_LINT_WARN_EMPTY_DOCS=false
```

Important behavior:

- integers are parsed and validated as integers
- booleans accept `true`, `false`, `1`, or `0`
- list and dictionary fields cannot be set through environment variables
- unknown `NEXUSOS_*` names emit a warning and are ignored
- names containing `SECRET`, `TOKEN`, `KEY`, or `PASSWORD` are ignored by the
  configuration loader and are not displayed

The most common field-name mappings are:

| TOML | Environment variable |
|---|---|
| `[workspace] name` | `NEXUSOS_WORKSPACE_NAME` |
| `[limits] max_file_size_bytes` | `NEXUSOS_MAX_FILE_SIZE_BYTES` |
| `[limits] symlink_policy` | `NEXUSOS_SYMLINK_POLICY` |
| `[indexing] chunk_max_chars` | `NEXUSOS_CHUNK_MAX_CHARS` |
| `[indexing] chunk_overlap_chars` | `NEXUSOS_CHUNK_OVERLAP_CHARS` |
| `[indexing] default_collection` | `NEXUSOS_DEFAULT_COLLECTION` |
| `[search] max_results` | `NEXUSOS_SEARCH_MAX_RESULTS` |
| `[search] snippet_length` | `NEXUSOS_SEARCH_SNIPPET_LENGTH` |
| `[server] host` | `NEXUSOS_SERVER_HOST` |
| `[server] port` | `NEXUSOS_SERVER_PORT` |
| `[mcp] enabled` | `NEXUSOS_MCP_ENABLED` |
| `[mcp] transport` | `NEXUSOS_MCP_TRANSPORT` |
| `[lint] max_file_size_bytes` | `NEXUSOS_LINT_MAX_FILE_SIZE_BYTES` |
| `[lint] warn_empty_docs` | `NEXUSOS_LINT_WARN_EMPTY_DOCS` |

`include_patterns`, `exclude_patterns`, and `collection_mappings` must be configured in
TOML because they are list or dictionary fields.

## Operational environment variables

Two documented environment variables are consumed outside the configuration
model. They are not configuration fields — they never appear in `config show`
— but the loader treats them as known names and does not emit the "unknown
`NEXUSOS_*` variable" warning for them.

| Variable | Semantics |
|---|---|
| `NEXUSOS_DENY_PATHS` | OS-path-separator list of absolute paths denied as workspace targets. Relative entries are ignored with a one-time warning; entries must be absolute (F-05). See [../SECURITY.md](../SECURITY.md). |
| `NEXUSOS_ALLOW_NON_LOOPBACK` | Set to `1` to allow MCP Streamable HTTP to bind a non-loopback host (F-08). See [mcp.md](mcp.md). |

## Internal fields

`root` and `index_path` are model fields present in `config show --json` but
are not user-facing tuning knobs in v0.1. `root` is set by the effective
loader; `index_path` is reserved for future use and the current indexer always
writes `.nexusos/index.sqlite3`. Do not rely on them. The full contract
inventory lives in [contracts.md](contracts.md).

## Viewing configuration

```bash
nexusos config show
nexusos config show --effective
nexusos config show --json
nexusos config show --effective --json
```

- `config show` displays file values merged over built-in defaults, without environment
  overrides.
- `--effective` includes recognized environment overrides.
- `--json` emits the display-safe model as JSON.

## MCP configuration

Start the default stdio transport:

```bash
nexusos mcp --workspace /path/to/workspace
```

Start Streamable HTTP explicitly:

```bash
nexusos serve --transport streamable-http --workspace /path/to/workspace
```

Generic stdio client configuration:

```json
{
  "mcpServers": {
    "nexusos": {
      "command": "nexusos",
      "args": ["mcp", "--workspace", "/path/to/workspace"]
    }
  }
}
```

See [mcp.md](mcp.md) for the tool and transport contract.
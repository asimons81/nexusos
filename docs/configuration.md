# Configuration

## Configuration File

Workspaces use `nexusos.toml` at the workspace root.

Example:

```toml
[workspace]
name = "my-knowledge-base"

[files]
include = ["**/*.md", "**/*.txt"]
exclude = ["**/.nexusos/**", "**/.git/**"]

[limits]
max_file_size_bytes = 10_485_760
symlink_policy = "ignore"

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
max_file_size_bytes = 5_242_880
warn_empty_docs = true
```

## MCP Server

The MCP server (`nexusos mcp` / `python -m nexusos.mcp --workspace PATH`)
speaks the Model Context Protocol over stdio (default). MCP clients launch
it as a subprocess and connect via JSON-RPC; nothing is printed to stdout
except protocol frames. `nexusos serve --transport streamable-http` serves
the same server over loopback-only Streamable HTTP (default 127.0.0.1:8765,
endpoint `/mcp`).

Configure it under `[mcp]`:

```toml
[mcp]
enabled = true          # set false to refuse MCP connections for this workspace
transport = "stdio"     # stdio | streamable-http
```

When `enabled = false`, the server refuses to start and exits non-zero, so
an MCP client cannot attach to a workspace that opted out.

### Client connection example

Point any MCP client at the `nexusos mcp` command, e.g. in an MCP client
config that supports stdio servers:

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

Equivalently, `python -m nexusos.mcp --workspace /path/to/workspace` runs
the same server from a source checkout.

## Precedence

1. Built-in defaults
2. `nexusos.toml` values
3. `NEXUSOS_*` environment variables
4. CLI flags

Lower numbers win. CLI flags override everything.

## Environment Variables

Any config key can be set via `NEXUSOS_<KEY>` (uppercase):

```bash
export NEXUSOS_SERVER_PORT=9000
export NEXUSOS_MAX_FILE_SIZE_BYTES=5000000
```

Secret-pattern env vars (`SECRET`, `TOKEN`, `KEY`, `PASSWORD`) are excluded from `--effective` display but still applied.

## Viewing Configuration

```bash
nexusos config show                  # Raw nexusos.toml values
nexusos config show --effective      # Resolved with env overrides
nexusos config show --json           # JSON output
```

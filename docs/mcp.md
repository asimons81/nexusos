# NexusOS MCP Server

NexusOS exposes a read-only view of a workspace index over the **Model
Context Protocol** (MCP). MCP clients — Hermes, Claude Desktop, Codex,
Claude Code, and others — can search, browse, read, and inspect a NexusOS
workspace without touching the source files.

## Transports

NexusOS v0.1.0 supports two MCP transports.

### stdio (default)

Speak JSON-RPC over stdin/stdout. Launch as a subprocess from an MCP client
config; nothing is printed to stdout before the protocol starts.

```bash
nexusos mcp --workspace /path/to/workspace
# or
nexusos serve --transport stdio --workspace /path/to/workspace
# or
python -m nexusos.mcp --workspace /path/to/workspace
```

Example client configuration:

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

### Streamable HTTP (loopback-only)

MCP over HTTP with Server-Sent-Events streaming, bound to the loopback
interface by default (127.0.0.1:8765, configurable via `[server] host` /
`[server] port` in `nexusos.toml`). The MCP endpoint is `/mcp`.

```bash
nexusos serve --transport streamable-http --workspace /path/to/workspace
```

Only the loopback address is ever bound by default; expose it externally
only if you add your own TLS/auth layer.

## Configuration

The `[mcp]` section in `nexusos.toml` controls the server:

```toml
[mcp]
enabled = true        # set false to disable the MCP server entirely
transport = "stdio"   # stdio | streamable-http
```

`NEXUSOS_MCP_ENABLED` and `NEXUSOS_MCP_TRANSPORT` environment variables
override these values.

## Tools

All tools are read-only and call the same shared service layer as the CLI
(`nexusos.services`). No source mutation tools are exposed.

| Tool      | Description                                                       |
|-----------|-------------------------------------------------------------------|
| `status`  | Workspace index status, counts, and staleness reasons             |
| `search`  | Full-text search over the FTS5 index (bm25-ranked, prefix match)  |
| `browse`  | List indexed documents, optionally filtered by collection         |
| `read`    | Read a document's content by id, relative path, or name          |
| `recent`  | Recently modified documents (newest first)                        |
| `links`   | Outgoing/incoming wiki links for a document with resolution state |
| `context` | Deterministic evidence packet: headings, siblings, linked docs    |
| `index`   | Run an index pass over the source corpus (derived state only)     |

> `index` writes only derived state inside `.nexusos/`; source files are
> never modified. All other tools never write anything.

### Example

```
Call tool "search" with {"term": "kernel"}
```

returns ranked hits with source path, line range, heading path, and a
highlighted snippet — the same output as `nexusos search`.

## Layering

The `nexusos.mcp` package is a top layer (sibling of `nexusos.cli`). It
imports `nexusos.services` only, never `core` internals or `indexing`
directly. Core, workspace, and indexing code never import MCP packages.

## Read-only guarantee

The integration suite proves that no CLI or MCP operation mutates source
files: `tests/security/test_isolation.py` snapshots the source tree and
asserts it is byte-for-byte unchanged after `lint`, `status`, and MCP
operations.

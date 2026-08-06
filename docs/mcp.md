# NexusOS MCP Server

NexusOS exposes a workspace index through the Model Context Protocol (MCP), allowing
agents to search, browse, read, inspect links, assemble deterministic context, check
status, and refresh derived state without editing source documents.

The current implementation is `v0.1.0-alpha.3`. Client compatibility is part of the
release-candidate validation plan in [../ROADMAP.md](../ROADMAP.md).

> **Contract freeze (A3-05):** the MCP tool set, input schemas, bounds, and error
> behavior are frozen for `v0.1.0-alpha.3` and locked by the contract test suite
> (`tests/contracts/`). See [contracts.md](contracts.md) for the machine-readable
> inventory of every tool, its schema, and its limits.

## Supported transports

### stdio

stdio is the default transport. An MCP client launches NexusOS as a subprocess and
communicates over stdin and stdout.

```bash
nexusos mcp --workspace /path/to/workspace
```

Equivalent forms:

```bash
nexusos serve --transport stdio --workspace /path/to/workspace
python -m nexusos.mcp --workspace /path/to/workspace
```

Nothing except MCP protocol frames is written to stdout after the server starts. Human
messages and failures must use stderr or protocol error responses.

Generic client configuration:

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

When running from a source checkout, use the executable created by `uv sync` or an
absolute command path that your client can launch.

### Streamable HTTP

Start MCP over Streamable HTTP:

```bash
nexusos serve --transport streamable-http --workspace /path/to/workspace
```

Defaults:

- host: `127.0.0.1`
- port: `8765`
- endpoint: `/mcp`

The bind address and port are configured through `[server]` or corresponding environment
variables. Loopback is the supported default.

A non-loopback bind is refused for the unauthenticated MCP endpoint unless the operator
explicitly opts in with `--allow-non-loopback` or `NEXUSOS_ALLOW_NON_LOOPBACK=1` (F-08
resolved). NexusOS is not an internet-facing multi-user service and does not provide a
complete remote authentication, authorization, or TLS layer. See
[../SECURITY.md](../SECURITY.md).

## MCP configuration

```toml
[mcp]
enabled = true
transport = "stdio"

[server]
host = "127.0.0.1"
port = 8765
```

Recognized environment overrides:

```bash
export NEXUSOS_MCP_ENABLED=true
export NEXUSOS_MCP_TRANSPORT=stdio
export NEXUSOS_SERVER_HOST=127.0.0.1
export NEXUSOS_SERVER_PORT=8765
```

When `mcp_enabled` is false, the server refuses to start for that workspace.

See [configuration.md](configuration.md) for precedence and validation behavior.

## Tool contract

NexusOS advertises strict input schemas with `additionalProperties: false`. Tool results
are returned as JSON-serializable structured content and a text representation. Typed
service errors become MCP tool errors rather than terminating the server.

| Tool | Purpose | Writes |
|---|---|---|
| `status` | Index state, counts, and staleness reasons | No |
| `search` | Ranked FTS5 retrieval with source-aware excerpts | No |
| `browse` | Indexed document metadata, optionally filtered | No |
| `read` | Bounded document reading by ID, path, or name | No |
| `recent` | Recently modified indexed documents | No |
| `links` | Incoming and outgoing wiki links with resolution state | No |
| `context` | Deterministic headings, siblings, and linked evidence | No |
| `index` | Run an incremental or requested index pass | Derived state only |

`index` may write inside `.nexusos/`. It must never modify workspace source documents.
All other tools are read-only and must not create a missing index as a side effect.

## Typical agent flow

A conservative agent sequence is:

1. call `status`
2. call `index` only when the index is missing or stale and the user permits refresh
3. call `search` to find candidate evidence
4. call `read`, `links`, or `context` for bounded inspection
5. cite returned source paths and line ranges in the agent response

Do not treat retrieval output as permission to modify the underlying files.

## Tool behavior

### `status`

Reports workspace identity, document and chunk counts, link-resolution counts, last index
state, and staleness reasons.

### `search`

Runs deterministic SQLite FTS5 search. Results include relative source path, line range,
heading path, rank information, and a highlighted excerpt.

Search is prefix-aware and case-insensitive. It does not invoke an LLM or embedding
service.

### `browse`

Lists indexed documents and metadata. Use it when the agent needs corpus shape rather
than a text query.

### `read`

Reads a bounded document or section by stable ID, relative path, or unambiguous name.
Ambiguous or missing identifiers return typed errors.

### `recent`

Returns recently modified documents in descending modification order.

### `links`

Returns outgoing and incoming wiki links with resolved, unresolved, or ambiguous state.

### `context`

Builds a deterministic evidence packet around a document, including headings, nearby
structure, and linked documents. It is not an LLM-generated summary.

### `index`

Uses the same indexing service as the CLI. Source discovery, parsing, graph resolution,
chunking, and persistence follow the same contract as `nexusos index`.

## Architecture boundary

The `nexusos.mcp` package is a top-level adapter beside `nexusos.cli`.

It must:

- import `nexusos.services`
- avoid direct imports from indexing internals
- avoid importing CLI code
- reuse service validation and typed errors
- preserve strict schemas and deterministic outputs

This boundary keeps the MCP interface from becoming a second implementation of NexusOS.
See [architecture.md](architecture.md).

## Source immutability

Security and integration tests must prove that MCP retrieval does not mutate source
files. A valid test snapshots source bytes, invokes the tool path, and compares the
source tree afterward.

Derived index changes from the `index` tool are expected and remain confined to
`.nexusos/`.

## MCP HTTP versus the inspection server

The CLI uses `serve` for two distinct modes:

```bash
# Read-only inspection API and bundled UI
nexusos serve --workspace /path/to/workspace

# MCP over Streamable HTTP
nexusos serve --transport streamable-http --workspace /path/to/workspace
```

These are separate protocols and endpoint contracts. Do not document `/api/*` inspection
routes as MCP endpoints, and do not document `/mcp` as part of the inspection API.

## Release validation

Before stable release, the roadmap requires representative client validation for:

- server startup and shutdown
- tool discovery
- strict input rejection
- status, search, read, context, and index calls
- missing and stale index behavior
- source immutability
- stdio protocol cleanliness
- Streamable HTTP endpoint behavior

Passing the protocol contract does not imply support for every client-specific UI or
configuration format.
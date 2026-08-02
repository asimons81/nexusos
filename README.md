# NexusOS

**Files you own. Memory your agents can trust.**

NexusOS is an open-source, local-first knowledge operating system for AI agents. It turns ordinary folders of Markdown files into a structured memory layer that agents can search, browse, inspect, and cite — through a CLI and MCP server.

## Status: Pre-release

Version **0.1.0-alpha.1** implements the safety shell and workspace
foundation; the **alpha.2** work adds the indexing kernel (deterministic
IDs, SQLite schema v1 with FTS5, transactional persistence,
exclusive-writer lock) plus `index`/`status`. Search and content navigation
(`search`, `browse`, `read`, `recent`, `links`, `context`) are implemented
on top of the index, and an MCP server (`nexusos mcp`, plus
`nexusos serve --transport stdio|streamable-http`) exposes them to MCP
clients. A workspace vault linter (`nexusos lint --workspace`) detects
broken links, orphans, duplicate slugs, stale indexes, and more. Embeddings
and vector search are not yet available.

## Installation

```bash
git clone https://github.com/asimons81/nexusOS
cd nexusOS
uv sync
```

## Current Commands

```bash
nexusos version              # Print version
nexusos init PATH            # Initialize a workspace (default: starter template)
nexusos init PATH --template blank   # Minimal workspace
nexusos init PATH --template starter # Full starter workspace
nexusos init PATH --dry-run  # Preview without writing
nexusos init PATH --adopt    # Adopt an existing directory
nexusos doctor               # Validate workspace health
nexusos config show          # Display configuration
nexusos config show --effective  # Resolved configuration
nexusos config show --json   # JSON output
nexusos index                # Index the workspace (incremental; --full rebuilds)
nexusos status               # Show index status and staleness
nexusos search TERM          # Full-text search (prefix matching, ranked)
nexusos browse               # List indexed documents
nexusos read ITEM            # Read a document by id/path/name
nexusos recent               # Recently modified documents
nexusos links ITEM           # Wiki-link graph for a document
nexusos context ITEM         # Headings, siblings, linked documents
nexusos mcp                  # Serve the workspace over MCP (stdio)
nexusos lint --workspace WS  # Lint a workspace vault (broken links, orphans, ...)
nexusos serve --transport stdio WS           # MCP over stdio
nexusos serve --transport streamable-http WS # MCP over loopback HTTP (127.0.0.1:8765)
```

## Developer Tooling

```bash
nexusos lint                 # Run ruff + mypy static checks over the kernel source
nexusos lint --tool mypy     # Run a single tool (ruff | format | mypy)
nexusos lint --json          # Machine-readable report
nexusos serve --workspace WS # Read-only HTTP server for kernel data (JSON + UI)
nexusos serve --port 8765    # Configurable port; SIGINT/SIGTERM shuts down cleanly
nexusos demo                 # Scripted walkthrough: synthetic vault, init→index→status→doctor
nexusos demo --path DIR      # Create the demo vault at DIR
nexusos demo --remove        # Delete the demo vault when done
```

`lint` doubles as a developer command for this repository: without
`--workspace` it runs the kernel's own tooling (ruff + mypy); with
`--workspace` it is the product vault linter. `serve` and `demo` operate on
the workspace index and on synthetic demo data. See [docs/linting.md](docs/linting.md)
and [docs/mcp.md](docs/mcp.md) for details.

## Workspace Structure

A starter workspace contains:

```
workspace/
├── nexusos.toml          # Configuration
├── README.md
├── SCHEMA.md
├── inbox/                # Unprocessed items
├── raw/                  # Source documents
│   ├── articles/
│   ├── conversations/
│   ├── notes/
│   └── transcripts/
├── wiki/                 # Knowledge base
│   ├── concepts/
│   ├── entities/
│   ├── projects/
│   ├── queries/
│   └── _archive/
├── ops/                  # Operational documents
│   ├── decisions/
│   ├── sops/
│   └── workflows/
├── mocs/                 # Maps of content
├── journal/              # Timestamped entries
└── .nexusos/             # Internal state (workspace.json)
```

## Safety Guarantees

- Never modifies source documents outside `.nexusos/`
- Denied-path system (`NEXUSOS_DENY_PATHS`) blocks dangerous locations
- Symlink escape detection
- Nested workspace prevention
- Atomic writes where practical
- No network access required

## Requirements

- Python 3.11+
- SQLite with FTS5 (for the indexing phase)

## License

Apache-2.0

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full plan.

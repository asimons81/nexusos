# NexusOS

**Files you own. Memory your agents can trust.**

NexusOS is an open-source, local-first knowledge operating system for AI agents. It turns ordinary folders of Markdown files into a structured memory layer that agents can search, browse, inspect, and cite — through a CLI and MCP server.

## Status: Pre-release

Version **0.1.0-alpha.1** implements the safety shell and workspace foundation. The internal indexing kernel for **0.1.0-alpha.2** (deterministic IDs, SQLite schema v1 with FTS5 preparation rows, transactional persistence, exclusive-writer lock) is implemented, but file discovery/parsing, the `index`/`status` commands, search, MCP server, linting, and embeddings are not yet available.

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
```

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

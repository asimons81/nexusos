<p align="center">
  <img src="assets/nexusos-branding.png" alt="NexusOS — Run your second brain" width="85%"/>
</p>

<p align="center">
  <a href="https://x.com/tonysimons_"><img src="https://img.shields.io/badge/X-%40tonysimons_-000000?style=flat-square&logo=x&logoColor=white" alt="X: @tonysimons_"/></a>
  <img src="https://img.shields.io/badge/version-0.1.0--alpha.2-blue?style=flat-square" alt="Version 0.1.0-alpha.2"/>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square" alt="License: Apache-2.0"/></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/status-alpha-orange?style=flat-square" alt="Status: alpha"/>
</p>

# NexusOS

**Files you own. Memory your agents can trust.**

NexusOS is an open-source, local-first knowledge operating system for AI agents. It turns ordinary folders of Markdown files into a structured memory layer that agents can search, browse, inspect, and cite — through a CLI and MCP server.

## Status: Pre-release

Version **0.1.0-alpha.2** implements the safety shell and workspace
foundation, the indexing kernel (deterministic IDs, SQLite schema v1 with
FTS5, transactional persistence, exclusive-writer lock), plus
`index`/`status`. Search and content navigation
(`search`, `browse`, `read`, `recent`, `links`, `context`) are implemented
on top of the index, and an MCP server (`nexusos mcp`, plus
`nexusos serve --transport stdio|streamable-http`) exposes them to MCP
clients. A workspace vault linter (`nexusos lint --workspace`) detects
broken links, orphans, duplicate slugs, stale indexes, and more. Embeddings
and vector search are not yet available.

## Installation

```bash
git clone https://github.com/asimons81/nexusos
cd nexusos
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
                             # /api/* reads require the printed X-NexusOS-Token
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

## Known Limitations (alpha)

The items below are accepted-for-alpha hardening backlog, documented so
reviewers and users understand the current boundary. Each is tracked for a
later release; none are secrets.

- **F-03 — TOCTOU in path-safety checks**: path-safety checks
  (`validate_within_workspace`, deny-path checks) are check-then-use — a
  concurrent actor that swaps a file between the check and the access can
  bypass the boundary. Accepted for alpha because NexusOS targets a local,
  single-user workspace where no untrusted process is expected to race the
  checks.
- **F-05 — relative deny-path entries resolve against the CWD**: a relative
  entry in `NEXUSOS_DENY_PATHS` resolves against the current working
  directory at check time, not the workspace root, so deny behavior depends
  on where the command is run from. Accepted for alpha; prefer absolute
  paths in `NEXUSOS_DENY_PATHS`.
- **F-06 — search limit values are not clamped**: `[search]` settings such as
  `max_results` and `snippet_length` accept any integer, including negative
  values — no range validation today. Accepted for alpha; a bad value
  surfaces as a runtime error rather than silent corruption.
- **F-07 — `check_symlink_escape` is defense-in-depth only**: the function is
  not called on the current code paths (indexing handles symlinks via
  `symlink_policy` instead), so it is effectively dead code retained as a
  safety net. Accepted for alpha; it will be wired into the real paths or
  removed.
- **F-08 — non-loopback bind is operator-opted**: binding the serve API to a
  non-loopback host (`--host 0.0.0.0` or similar) prints a warning and
  proceeds — the operator overrides the loopback default and assumes the
  risk. The F-02 protections (Host allowlist, `X-NexusOS-Token`) still apply,
  but the read-only serve API becomes reachable on the network.

## Requirements

- Python 3.11+
- SQLite with FTS5 (for the indexing phase)

## License

Apache-2.0

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full plan.

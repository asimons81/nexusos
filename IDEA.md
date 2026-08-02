# NexusOS

## Project Idea

Build **NexusOS**, an open-source, local-first knowledge operating system for AI agents.

NexusOS should turn an ordinary folder of Markdown and text files into a structured memory layer that agents can search, browse, inspect, and cite through a CLI and Model Context Protocol server.

The user's files remain the source of truth. NexusOS must not require a proprietary file format, hosted account, external database, embedding service, or language model to perform its core functions.

The first release should be a safe, deterministic, read-only memory kernel.

## Core Product Promise

**Files you own. Memory your agents can trust.**

NexusOS should let users:

* Keep their knowledge in normal Markdown files
* Index documents locally using SQLite and FTS5
* Search their knowledge with line-aware excerpts
* Browse collections and document metadata
* Read bounded sections of documents
* Inspect incoming, outgoing, and unresolved wiki links
* Find recently modified documents
* Generate deterministic evidence packets for a topic
* Detect broken links, invalid metadata, orphan pages, and structural drift
* Connect the knowledge system to Hermes, ChatGPT, Codex, Claude Code, and other MCP-compatible clients

Every search result and evidence excerpt should preserve its source document, relative path, heading, and line range.

## First Release

Target version:

`v0.1.0-alpha.1`

The first release should include:

* Python 3.11+
* `uv` for packaging and dependency management
* Typer-based CLI
* SQLite metadata database
* SQLite FTS5 search
* Markdown and plain-text indexing
* YAML frontmatter parsing
* Markdown heading extraction
* Deterministic document chunking
* Wiki-link graph indexing
* Incremental reindexing
* Vault linting and health checks
* JSON and human-readable CLI output
* Read-only MCP server
* MCP stdio transport
* Loopback-only Streamable HTTP transport
* Synthetic demo vault
* Linux, macOS, Windows, and WSL2 support
* Automated tests and release workflow

## Required CLI Commands

```bash
nexusos init
nexusos doctor
nexusos index
nexusos status
nexusos browse
nexusos search
nexusos read
nexusos recent
nexusos links
nexusos context
nexusos lint
nexusos serve
nexusos demo
nexusos version
```

## Required MCP Tools

The initial MCP server should expose only read operations:

* `nexusos_status`
* `nexusos_browse`
* `nexusos_search`
* `nexusos_read`
* `nexusos_recent`
* `nexusos_links`
* `nexusos_context`

All MCP tools and CLI commands must call the same shared service layer.

## Safety and Isolation

This project is inspired by an existing private system named Nexus, but NexusOS must be completely separate from it.

Do not inspect, modify, import, migrate, reuse, or initialize inside the existing private Nexus.

NexusOS must use its own namespace:

* CLI: `nexusos`
* Python package: `nexusos`
* Environment variables: `NEXUSOS_*`
* Workspace state: `.nexusos/`
* Configuration: `nexusos.toml`
* Default database: `.nexusos/index.sqlite3`
* Document IDs: `nxo_doc_*`
* Chunk IDs: `nxo_chk_*`
* Default HTTP port: `8765`
* MCP tools: `nexusos_*`

The system must support denied filesystem paths through `NEXUSOS_DENY_PATHS`.

Tests and examples must use synthetic documents only.

## Read-Only Contract

NexusOS v0.1 must never edit indexed source documents.

The only allowed writes are:

* Files explicitly created by `nexusos init`
* Derived state inside `.nexusos/`
* Logs or reports explicitly requested by the user

The MCP server must expose no source mutation tools in v0.1.

The integration test suite must verify that all source files remain byte-for-byte unchanged after CLI and MCP operations.

## Architecture

Use the following dependency direction:

```text
configuration and core models
        ↓
file discovery and parsing
        ↓
indexing and link graph
        ↓
retrieval and linting
        ↓
shared service layer
        ↓
CLI and MCP adapters
```

The core must not depend on Typer, Rich, or MCP packages.

The index must be disposable and completely rebuildable from source files.

## Workspace Structure

A starter workspace should resemble:

```text
workspace/
├── nexusos.toml
├── SCHEMA.md
├── README.md
├── inbox/
├── raw/
├── wiki/
│   ├── concepts/
│   ├── entities/
│   ├── projects/
│   ├── queries/
│   └── _archive/
├── ops/
│   ├── decisions/
│   ├── sops/
│   └── workflows/
├── mocs/
├── journal/
└── .nexusos/
    ├── workspace.json
    └── index.sqlite3
```

## Search and Evidence Requirements

Search must be deterministic and use SQLite FTS5.

Search results should return:

* Document ID
* Chunk ID
* Title
* Relative path
* Collection
* Authority class
* Heading path
* Start line
* End line
* Excerpt
* Diagnostic relevance score
* Local citation URI

The `context` feature should create a bounded evidence packet from multiple relevant sources.

It must not use an LLM, invent conclusions, or describe itself as a summary.

## Linting Requirements

The initial linter should detect:

* Invalid YAML frontmatter
* Missing required metadata
* Unsupported statuses
* Unsupported tags
* Broken wiki links
* Ambiguous wiki links
* Orphan pages
* Underlinked wiki pages
* Self-links
* Duplicate slugs
* Duplicate content
* Oversized files
* Empty documents
* Files outside recognized collections
* Symlinks escaping the workspace
* Database paths outside the workspace
* Stale indexes
* Stale generated documents when configured

## Explicit Non-Goals for v0.1

Do not build:

* A graphical interface
* Embeddings
* A vector database
* Autonomous document writing
* Source mutation through MCP
* Cloud hosting
* OAuth
* Multi-user collaboration
* Synchronization
* External connectors
* Web crawling
* Private Nexus migration
* Agent orchestration
* A plugin marketplace

These belong to later releases.

## Future Direction

NexusOS may eventually grow into:

1. A controlled ingestion system for web pages, PDFs, documents, and external services
2. A guarded write system using proposals, diffs, approvals, transactions, and rollback
3. An operational dashboard with projects, decisions, briefings, and generated maps of content
4. A shared memory plane for fleets of specialized agents
5. A local graphical interface called NexusOS Studio
6. Encrypted synchronization and team collaboration
7. Connectors for Gmail, Google Drive, GitHub, Slack, calendars, and feeds
8. A managed NexusOS Cloud service with hosted MCP, OAuth, backups, and team administration

The open-source local version must remain fully useful. Paid products should sell hosting, collaboration, managed security, connectors, synchronization, and convenience rather than intentionally weakening the core.

## Build Priorities

Implement in this order:

1. Repository and isolation safeguards
2. Workspace initialization and configuration
3. File discovery and Markdown parsing
4. SQLite schema and incremental indexing
5. Search, browse, read, recent, links, and context
6. Linting and staleness detection
7. Read-only MCP adapter
8. Cross-platform tests
9. Documentation and release automation

Do not move to later phases until the previous phase has tests and working verification.

## Definition of Success

The first release is successful when a new user can:

```bash
nexusos init my-vault --template starter
cd my-vault
nexusos doctor
nexusos index
nexusos search "agent memory"
nexusos context "current project priorities"
nexusos lint
nexusos serve --transport stdio
```

The system must produce deterministic, source-cited results without modifying the user's knowledge files or requiring any remote service.

Build the kernel first.

It should be safe, local, inspectable, fast, rebuildable, and boringly reliable.

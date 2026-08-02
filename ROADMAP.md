# Roadmap

## v0.1.0-alpha.1 — Safety Shell + Workspace Foundation

**Status: COMPLETE**

- [x] Repository structure and project tooling
- [x] Package metadata and CLI entry point
- [x] Core error classes
- [x] Path safety and workspace boundaries
- [x] `NEXUSOS_DENY_PATHS` support
- [x] Symlink escape detection
- [x] Nested workspace detection
- [x] `nexusos version`
- [x] `nexusos init` (blank/starter templates, --dry-run, --adopt)
- [x] `nexusos doctor`
- [x] `nexusos config show`
- [x] Unit and security tests
- [x] CI matrix (Linux, macOS, Windows)
- [x] Documentation (README, AGENTS, CHANGELOG, docs/)

## v0.1.0-alpha.2 — Indexing

**Status: COMPLETE**

- [x] SQLite schema with FTS5 (indexing kernel: deterministic IDs, transactional persistence, exclusive-writer lock, run records)
- [x] Markdown and plain-text file discovery
- [x] YAML frontmatter parsing
- [x] Markdown heading extraction
- [x] Wiki-link extraction and graph resolution
- [x] Deterministic chunking
- [x] Incremental reindexing (added/changed/deleted detection, full rebuild)
- [x] `nexusos index` and `nexusos status` commands
- [x] Strict configuration validation (unknown TOML sections/keys rejected)

## v0.1.0-alpha.3 — Search & Retrieval

**Status: COMPLETE**

- [x] `nexusos search` with line-aware excerpts (SQLite FTS5, bm25-ranked, prefix matching, `--json`)
- [x] `nexusos browse` for collection and document metadata
- [x] `nexusos read` with bounded section reading
- [x] `nexusos recent` for recently modified documents
- [x] `nexusos links` for wiki-link graph inspection
- [x] `nexusos context` for deterministic evidence packets

## v0.1.0-alpha.4 — Linting & MCP

**Status: COMPLETE**

- [x] `nexusos lint` with stale/broken detection (workspace vault linter: broken links, ambiguous links, invalid frontmatter, orphans, duplicate slugs, stale index, oversized/empty documents, symlink escapes, files outside collections)
- [x] Read-only MCP server (`nexusos mcp`, `nexusos serve --transport stdio`)
- [x] MCP stdio transport with strict tool schemas (status, search, browse, read, recent, links, context, index)
- [x] Loopback-only Streamable HTTP transport (`nexusos serve --transport streamable-http`, default 127.0.0.1:8765)
- [x] Synthetic demo vault

## v0.1.0 — Stable Release

**Status: IN PROGRESS**

- [x] Full test coverage
- [x] Read-only contract verified (source immutability security tests)
- [ ] Cross-platform validation
- [ ] Published to PyPI
- [x] Complete documentation (docs/mcp.md, docs/linting.md)

## Future

- Ingestion pipelines (web, PDF, external services)
- Guarded write system (proposals, diffs, approvals)
- Operational dashboard (NexusOS Studio)
- Fleet memory plane for multi-agent coordination
- Encrypted sync and team collaboration
- Cloud service with hosted MCP and OAuth

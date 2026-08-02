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

**Status: IN PROGRESS** (kernel core done; pipeline + CLI pending)

- [x] SQLite schema with FTS5 (indexing kernel: deterministic IDs, transactional persistence, exclusive-writer lock, run records)
- [ ] Markdown and plain-text file discovery
- [ ] YAML frontmatter parsing
- [ ] Markdown heading extraction
- [ ] Incremental reindexing (kernel `add/update/upsert/remove` API ready; discovery/parsing pipeline and CLI pending)
- [ ] `nexusos index` and `nexusos status` commands

## v0.1.0-alpha.3 — Search & Retrieval

- [x] `nexusos search` with line-aware excerpts (SQLite FTS5, bm25-ranked, prefix matching, `--json`)
- [x] `nexusos browse` for collection and document metadata
- [x] `nexusos read` with bounded section reading
- [x] `nexusos recent` for recently modified documents
- [x] `nexusos links` for wiki-link graph inspection
- [x] `nexusos context` for deterministic evidence packets

## v0.1.0-alpha.4 — Linting & MCP

- `nexusos lint` with stale/broken detection
- Read-only MCP server
- MCP stdio transport
- Loopback-only Streamable HTTP transport
- Synthetic demo vault

## v0.1.0 — Stable Release

- Full test coverage
- Cross-platform validation
- Published to PyPI
- Complete documentation

## Future

- Ingestion pipelines (web, PDF, external services)
- Guarded write system (proposals, diffs, approvals)
- Operational dashboard (NexusOS Studio)
- Fleet memory plane for multi-agent coordination
- Encrypted sync and team collaboration
- Cloud service with hosted MCP and OAuth

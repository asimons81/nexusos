# NexusOS v0.1.0-alpha.3 — Release Notes

**Release:** `v0.1.0-alpha.3` (PEP 440: `0.1.0a3`) · **Status:** pre-release
**Commit:** `ed46376631b0b2b75eb0f648aafec2e4c1180e30`
**Source:** [CHANGELOG.md](CHANGELOG.md) · [Install guide](docs/install.md) · [Artifact manifest](docs/release/v0.1.0-manifest.md)

NexusOS is a local-first, read-only knowledge operating system for AI agents.
This is the **hardening and release-infrastructure** prerelease on the road to
`v0.1.0`: every A3 roadmap task is complete, public contracts are frozen,
security review is done, and the artifacts below were built and verified from
the exact release commit.

## What's in this release

All of the `v0.1.0-alpha.2` core feature scope (workspace init, deterministic
Markdown/text indexing into SQLite + FTS5, search/browse/read/recent/links/
context, linting, MCP over stdio and Streamable HTTP, read-only HTTP API and
inspection UI), plus the release-hardening work:

### Release hardening (A3 tasks, all complete)

- **A3-01 — Accepted alpha findings resolved.** Path-safety TOCTOU (F-03),
  relative deny-path resolution (F-05), unbounded result limits (F-06), dead
  symlink-escape defense (F-07), and non-loopback bind policy (F-08) all
  fixed with regression tests.
- **A3-02 — Full CI matrix.** The complete test suite (unit + integration +
  security) now runs on Linux/macOS/Windows × Python 3.11/3.12/3.13. Green on
  `main`.
- **A3-03 — Measured coverage policy.** Aggregate gate `fail_under = 80`
  (measured baseline 84–85%), security-critical module floors, per-leg
  coverage artifacts. No more unmeasured "full coverage" claims.
- **A3-04 — Verified artifacts.** sdist + wheel built from the release
  commit, `twine check` passed, clean-environment installs verified (see
  Artifacts below).
- **A3-05 — Public contract freeze.** `docs/contracts.md` inventories every
  CLI command/option, exit code, config key, env var, JSON shape, and MCP
  tool schema; 142 contract tests lock the surface.
- **A3-06 — Docs verified as executable assets.** Install guide, release
  notes, examples, and release procedure all validated against implemented
  behavior.
- **A3-07 — Security release review.** Findings F-09…F-14 (issues #4–#9)
  fixed: lock/DB file permissions (0600), no token embedding on non-loopback
  binds, byte-for-byte source-immutability tests across CLI/HTTP/MCP, search
  term-length bounds, path-traversal tests, and a full threat model in
  `docs/security-model.md` with a concrete private vulnerability-reporting
  path. No release-blocking finding remains.

### Validation evidence (RC-03 / RC-04)

- **RC-03 — MCP client compatibility:** Streamable HTTP with the official MCP
  Python SDK and a raw JSON-RPC client — handshake, tool discovery (8 tools),
  strict-schema rejection, status/search/read/context/index, source
  immutability proof.
- **RC-04 — Upgrade/schema validation:** alpha.2 workspaces open directly,
  schema v1→v2 migration, clear refusal of newer schemas, derived-state
  delete+rebuild without source loss, downgrade expectations documented.

## Repository gate (release commit `ed46376`)

| Check | Result |
|---|---|
| `ruff check` | clean |
| `ruff format --check` | clean (748 files) |
| `mypy src` | clean (47 files) |
| `pytest -q` | **614 passed, 1 skipped** (skip = macOS-only smoke) |
| `nexusos version` | `nexusos 0.1.0-alpha.3` |
| `twine check dist/*` | PASSED |
| CI (main) | green — 9-leg matrix (Linux/macOS/Windows × 3.11/3.12/3.13) |

## Artifacts

| Artifact | SHA-256 |
|---|---|
| `nexusos-0.1.0a3-py3-none-any.whl` | `e8cee62283801235026635587c876b3360d7ad421873de3c0e99aee6c6156038` |
| `nexusos-0.1.0a3.tar.gz` | `45ddb49b2668579b34d43b48eeb7fcc496fcb3b85876c1dbc11709c087de277e` |

Clean-install verified from both artifacts (fresh venvs, no source checkout):
`version`, `--help`, `init`, `doctor` (13/13), `index`, `status`, `search`,
`lint`, `demo`, and MCP stdio handshake (serverInfo `0.1.0-alpha.3`,
8 tools, `status: ready`, `read_only: true`).

## Security

- Source files are never mutated by any CLI, HTTP, or MCP retrieval path
  (byte-for-byte immutability tests).
- MCP Streamable HTTP is unauthenticated and **loopback-only by default**;
  non-loopback binds are refused unless the operator explicitly overrides
  (`--allow-non-loopback` / `NEXUSOS_ALLOW_NON_LOOPBACK=1`). Do not expose it
  to an untrusted network without an external security layer.
- Vulnerability reports: [private advisory flow](SECURITY.md).

## Known limitations

- Pre-release software: not yet on PyPI (RC-01 pending).
- macOS/Windows clean-install validation pending at RC-02 (CI-tested on all
  three platforms).
- No embeddings/vector search, no ingestion connectors, no source mutation,
  no cloud/multi-user features — these are post-v0.1 direction.

## Upgrade notes

- Run `nexusos index` once after upgrading to apply schema v1→v2 migration.
- `nexusos serve` API callers need the per-process `X-NexusOS-Token` header
  plus a loopback `Host`.
- Deny paths must be absolute; result limits are enforced; non-loopback MCP
  bind is refused unless explicitly allowed.

## Changelog

Full changelog: [CHANGELOG.md](CHANGELOG.md)

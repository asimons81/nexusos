# Security Model

> Status: maintained by roadmap task **A3-07** (adversarial security release
> review, `v0.1.0-alpha.3`). The supported deployment boundary and the
> vulnerability reporting path live in [SECURITY.md](../../SECURITY.md); this
> document is the threat model, the defense-in-depth inventory, and the
> per-review-area evidence record. When implementation, tests, or docs
> disagree, correct the contract deliberately across every affected document
> (AGENTS.md Documentation contract).

## 1. Supported deployment boundary

NexusOS v0.1 is a **local, single-user memory kernel**:

- Core workflows (`init`, `index`, `status`, `search`, `read`, `browse`,
  `recent`, `links`, `context`, `lint`) require no network access.
- MCP stdio runs as a local subprocess spawned by the MCP client.
- The kernel-data HTTP server and MCP Streamable HTTP bind to **loopback by
  default** (`127.0.0.1`).
- There is **no multi-user authentication or authorization** and no
  internet-facing TLS termination in v0.1.

The HTTP surfaces are developer/inspection tooling, not internet services:

- **Kernel-data HTTP server** (`nexusos serve --transport http`): validates
  `Host`, rejects foreign `Origin`, requires a per-process `X-NexusOS-Token`
  for every `/api/*` read, and disables caching for the injected UI page.
  On a non-loopback bind it warns and proceeds; the token is the only access
  control and is **not embedded** in the served UI page on such binds
  (A3-07 F-10).
- **MCP Streamable HTTP** (`nexusos serve --transport streamable-http`):
  unauthenticated JSON-RPC that includes the derived-state `index` write
  tool. A non-loopback bind is **refused** unless the operator explicitly
  opts in with `--allow-non-loopback` or `NEXUSOS_ALLOW_NON_LOOPBACK=1`
  (F-08).

Neither surface is a complete internet-facing security layer. Exposing either
to an untrusted network requires an external security layer appropriate to the
deployment (reverse proxy, TLS, authentication, network policy). See
[SECURITY.md](../../SECURITY.md) for the full boundary statement and out-of-scope
controls.

## 2. Threat model

Trust domains, in increasing order of privilege:

1. **Source content** — Markdown/text files inside the workspace. Untrusted
   bytes; may contain malicious symlinks, huge files, or malformed frontmatter.
2. **Index-derived state** — `.nexusos/` (SQLite database, WAL/SHM, lock,
   workspace.json). Disposable and rebuildable from sources.
3. **Local operator** — the account running NexusOS. Fully trusted.
4. **Local processes / other OS users** — can read world-readable files and
   reach loopback ports. Partially trusted (mitigations: owner-only state
   files, Host/Origin checks, per-process token).
5. **Remote network clients** — only reach NexusOS if the operator binds
   non-loopback. Untrusted; mitigated by explicit opt-in, Host/Origin checks,
   and the token, but **not** a complete security layer.

| # | Threat | Impact | Mitigation | Evidence |
|---|--------|--------|-----------|----------|
| T1 | Workspace root/home/OS-reserved path chosen as workspace | Corruption of system state | `resolve_safe` / `forbid_root_or_home` / built-in forbidden prefixes | `tests/security/test_isolation.py`, `tests/unit/test_path_safety.py` |
| T2 | Nested workspace inside another | Cross-workspace confusion | Ancestor + descendant checks on init/doctor | `tests/unit/test_path_safety.py` |
| T3 | Deny-path circumvention (relative or CWD-dependent entries) | Silent protection misses | Absolute-only `NEXUSOS_DENY_PATHS` entries + warning (F-05) | `tests/security/test_a3_01_release_fixes.py` |
| T4 | Symlink escape during indexing | Outside content ingested | `check_symlink_escape` at init/doctor; scanner boundary checks; O_NOFOLLOW read path (F-07, F-03) | `tests/security/test_a3_01_release_fixes.py` |
| T5 | Index read-path TOCTOU (file swapped after scan) | Outside content ingested | `read_source_text_safe` re-validates boundary + `O_NOFOLLOW` at read time (F-03) | `tests/security/test_a3_01_release_fixes.py` |
| T6 | Source mutation through retrieval | Data loss / contract breach | Read-only service layer; no write path to sources in v0.1 | `tests/security/test_a3_07_security_review.py` (F-11), `tests/security/test_isolation.py`, `tests/integration/test_mcp_streamable_http.py` |
| T7 | Other local users read derived state (index DB, lock) | Content/metadata disclosure | Owner-only state files: `index.sqlite3` 0600 (F-12), `index.lock` 0600 (F-09), `workspace.json` 0600 | `tests/security/test_a3_07_security_review.py` |
| T8 | Temp-file symlink pre-staging | Write to attacker-chosen path | `tempfile.mkstemp` + `os.replace` (unpredictable names, atomic rename) | `tests/unit/test_path_safety.py`, `tests/unit/test_init.py` |
| T9 | Corrupt/foreign index DB | Wrong data or upgrade confusion | Schema versioning, workspace-id binding, future-schema refusal (RC-04) | `tests/integration/test_upgrade_schema_validation.py` |
| T10 | DNS rebinding / foreign Host header on kernel-data server | Cross-origin read | Loopback Host allowlist, single-Host enforcement, malformed-bracket rejection (F-01/F-02) | `tests/unit/test_serve_security.py` |
| T11 | Cross-origin browser request with stolen token | Unauthorized API read | Loopback-Origin-only policy on `/api/*` | `tests/unit/test_serve_security.py` |
| T12 | Token exfiltration via unauthenticated root page | Access control bypass | Token embedded in UI page only on loopback binds; omitted on non-loopback (F-10) | `tests/security/test_a3_07_security_review.py` |
| T13 | Non-loopback MCP exposure (unauthenticated write-capable endpoint) | Remote write of derived state | Refuse non-loopback unless explicit override (F-08); documented boundary | `tests/security/test_a3_01_release_fixes.py`, `tests/unit/test_serve_security.py` |
| T14 | Malformed/oversized search input on MCP | Local DoS, unbounded FTS work | Shared `MAX_SEARCH_TERM_LENGTH` (F-13); FTS query builder quotes all words; range-validated limits (F-06) | `tests/security/test_a3_07_security_review.py`, `tests/unit/test_search.py` |
| T15 | Path traversal on HTTP endpoints (`/api/documents/...`, `/ui/...`) | Read outside intended set | Document lookups are index-relative (no filesystem read); UI asset path resolved + boundary-checked | `tests/security/test_a3_07_security_review.py`, `tests/unit/test_serve_security.py` |
| T16 | Secret leakage in configuration display | Credential exposure | Secret-pattern env vars excluded from overrides and `--effective` display | `tests/unit/test_config.py` |
| T17 | Stale/wrong lock deletion by another process | Concurrent write corruption | PID-liveness + ownership-token checks; stale lock reclaim only when owner dead | `tests/unit/test_index_lock.py` |
| T18 | Unbounded result sets (`--limit -1`) | DoS / accidental full dump | Shared min/max bounds across CLI/config/JSON/MCP (F-06) | `tests/security/test_a3_01_release_fixes.py` |

## 3. Defense-in-depth inventory

### 3.1 Filesystem boundary

- `nexusos.core.path_safety` owns all boundary logic: `is_denied_path`,
  `deny`, `forbid_root_or_home`, `check_nesting`, `validate_within_workspace`,
  `read_source_text_safe`, `find_symlink_escapes`, `check_symlink_escape`.
- Deny list is absolute-only (F-05). Built-in forbidden prefixes cover `/etc`,
  `/proc`, `/sys`, `/dev`, `/boot`, `/run`, `C:\Windows`, `C:\Program Files`.
- The indexer re-validates the boundary immediately before reading each file
  and opens with `O_NOFOLLOW` where the platform supports it (F-03).
- Residual TOCTOU: a concurrent attacker with write access to the workspace
  directory can still race the final `os.open` (e.g. swap an intermediate
  directory). This is an accepted, documented residual; it requires local
  write access inside the workspace, which the single-user model treats as
  operator trust. Do not run NexusOS on directories writable by untrusted
  parties.

### 3.2 State files and permissions

| File | Purpose | Permissions | Rationale |
|---|---|---|---|
| `.nexusos/workspace.json` | Workspace identity | 0600 (mkstemp) | Identity metadata |
| `.nexusos/index.lock` | Exclusive writer lock | 0600 (F-09) | Contains ownership token, pid, host, run id |
| `.nexusos/index.sqlite3` (+ `-wal`/`-shm`) | Index database | 0600 (F-12) | Mirrors source content |
| Temp files | Atomic writes | mkstemp (0600) + `os.replace` | Unpredictable names, no symlink following |

Index writes are transactional (`BEGIN IMMEDIATE`), protected by an exclusive
writer lock, and schema-versioned. Read-only commands (`status`, `search`,
`read`, `browse`, `doctor`) never create the index database and open it with a
`mode=ro` URI when present.

### 3.3 HTTP surface

- `Host` allowlist: only `127.0.0.1`, `localhost`, `::1` (after stripping a
  port and IPv6 brackets). Malformed bracketed forms never normalize to
  loopback. Duplicate `Host` headers are rejected (RFC 7230 §5.4).
- `/api/*` requires a per-process token compared with
  `secrets.compare_digest`; foreign `Origin` is rejected even with a valid
  token.
- `Cache-Control: no-store` on the token-bearing UI page and API responses.
- `/api/documents/...` resolves against the index by relative path — it never
  touches the filesystem, so traversal attempts cannot read outside files.
- `/ui/...` resolves the candidate against the packaged UI directory and
  rejects anything outside it.

### 3.4 MCP surface

- stdio: local subprocess; no network exposure.
- Streamable HTTP: loopback-only by default; non-loopback refused unless
  `--allow-non-loopback` / `NEXUSOS_ALLOW_NON_LOOPBACK=1` (F-08).
- Strict tool argument schemas: unknown keys rejected, numeric bounds
  enforced, search term length capped (F-13).
- `index` tool writes derived state only; retrieval tools (`search`, `read`,
  `browse`, `recent`, `links`, `context`, `status`) are read-only and never
  create the database.

### 3.5 Configuration display

`config show --effective` renders the model through `to_safe_dict()`, which
excludes secret-pattern environment variables (`*SECRET*`, `*TOKEN*`,
`*KEY*`, `*PASSWORD*`) before overrides are applied.

## 4. Accepted limitations (non-blocking)

These are explicit, documented trade-offs that are **not** release blockers
for v0.1:

- **MCP Streamable HTTP on loopback is unauthenticated** (by design). Any
  local process can reach it and invoke read tools or the `index` write tool.
  The loopback default and the non-loopback refusal are the controls; the
  deployment boundary is single-user local.
- **Kernel-data HTTP token on loopback** is a per-process secret intended to
  gate casual/cross-origin access. It is embedded in the served UI page on
  loopback binds so the bundled frontend works without manual headers; it is
  **not** a substitute for authentication against other local OS users or an
  untrusted network.
- **Residual TOCTOU** on the indexer read path (see §3.1). Requires local
  write access inside the workspace.
- **Search term bound** (`MAX_SEARCH_TERM_LENGTH`) is generous (10,000 chars)
  and only prevents unbounded single-request work; it is not a rate limit.
- **State-file permissions are owner-only on POSIX**; Windows ignores POSIX
  mode bits (ACLs govern there).
- **No downgrade path** for schema versions (RC-04). See
  `docs/releasing.md`.

## 5. Isolation from private systems

This project shares a design philosophy with a private system but is
completely isolated: different namespace (`nexusos`), different CLI/package/
env/state directory, no shared code, no imports or references to private
paths, and tests use synthetic data only.

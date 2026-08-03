# NexusOS v0.1.0-alpha.2 — Release Notes

**Release:** 0.1.0-alpha.2
**Baseline:** d8f6950 (v0.1.0-alpha.1) → `62b00f5`
**Status:** Release candidate — all review findings fixed, test gate green

NexusOS is a local-first, read-only knowledge index for Markdown vaults: it
scans a folder of Markdown and plaintext files, builds a versioned SQLite/FTS5
index, and exposes search, navigation, linting, and an MCP server — all without
ever mutating your source files.

v0.1.0-alpha.2 is the hardening release. It ships no new surface area beyond
the alpha.1 feature set; instead it fixes every finding from the independent
release-readiness review — two high-severity fail-safes, two medium security
issues, and four medium diagnostics defects — and adds the regression tests
that pin each one.

---

## Release announcement

> NexusOS v0.1.0-alpha.2 is out — the hardening release that closes every
> finding from our release-readiness review. We fixed the two high-severity
> fail-safes (a pathological-heading freeze in `nexusos index` and a silent
> unreadable-directory skip that could report success over an empty index), the
> two security issues found in the serve transport (temp-file symlink overwrite
> and DNS-rebinding exfiltration), and four diagnostics gaps (stale-index
> detection, root-file discovery, clean CLI errors, and surfaced warnings).
> The test gate is now 414 passing with 44 new regression tests, and ruff/mypy
> are clean. If you run the alpha.1 line, just re-run `nexusos index` once to
> pick up the schema migration — nothing else changes. Full notes and the
> upgrade guide are in RELEASE_NOTES.md.

---

## Summary of changes

- **All 8 release-blocking findings from the readiness review are fixed.**
  The test gate grew from 363 to **414 passing tests** (ruff check/format and
  mypy clean) with 44 dedicated regression test functions covering every fix.
- **Index schema migrated v1 → v2** (`index_runs.warnings_json`) to persist
  discovery warning details. Migration is automatic on the next `nexusos index`.
- **Hardened the HTTP server** (`nexusos serve`) against DNS-rebinding and
  unauthenticated index reads.
- **Cleaner CLI failure modes** across config, init, and serve — no more raw
  tracebacks, correct exit codes.

## Fixed

| Finding | Severity | What was fixed |
|---|---|---|
| F1 | HIGH | **O(n³) heading-path hang.** Indexing a Markdown file with thousands of headings could freeze `nexusos index` for 20+ seconds while holding the exclusive writer lock. Heading hierarchy now builds in a single-pass O(n) walk; a 5,000-heading file indexes in under a second. |
| F2 | HIGH | **Silent unreadable-directory skip.** An unreadable source directory was silently skipped, so `nexusos index` could report success with zero files and zero warnings. Discovery now surfaces `unreadable_directory` warnings, and `nexusos doctor` fails its `source_dirs_readable` check when one exists. |
| F-01 | MED | **Temp-file symlink overwrite.** Atomic writes used a predictable temp path, letting a pre-staged symlink cause an arbitrary file write. Writes now use unpredictable `mkstemp` names + `os.replace()`, and `init --adopt` refuses any directory whose `.nexusos` is a symlink, a plain file, or already seeded. |
| F-02 | MED | **Host-header / DNS-rebinding exfiltration.** The HTTP serve transport accepted any Host header with no auth, so a rebinding page could read the full indexed corpus. It now rejects non-loopback Host headers (403), requires a per-process `X-NexusOS-Token` for all `/api/*` reads, and rejects foreign Origins even with a valid token. |
| FD1 | MED | **Stale-index detection missed content-only edits.** `status`/`lint` compared only path sets, so rewriting a file in place never flagged the index as stale. Detection now compares mtime/size signatures. |
| FD2 | MED | **Root-level files excluded by default.** The default `**/*.md` include never matched root-level files (e.g. `README.md`, root notes). Globstar patterns now match zero-or-more directories, so root files are discovered and indexed. |
| F3 | MED | **Raw CLI tracebacks.** `config show` on invalid TOML, `init` into a bad path, and `serve --port 99999` crashed with Rich traceback panels. These now print clean `Error: ...` messages with correct exit codes (1/2), matching the rest of the CLI. |
| F4/F5/F7 | MED | **Diagnostics gaps.** A read-only index database was mislabeled "corrupt" — it is now detected as a permission error and read commands fall back to read-only URI opens (F4). `NEXUSOS_*` env overrides are type-validated at load, naming the offending variable (F5). Discovery warnings are now persisted and surfaced with type/path/message in human and JSON index output (F7). |

## Upgrade notes

- **Run `nexusos index` once after upgrading.** This applies the schema v1→v2
  migration and picks up the new warning details. Read-only commands never
  migrate; if they hit an older schema they print a clear "run `nexusos index`"
  message instead of failing cryptically.
- **Scripts that call the serve HTTP API need a token.** `nexusos serve` prints
  a per-process `X-NexusOS-Token` at startup (and injects it into the bundled UI
  automatically). Any direct caller of `/api/*` must read that token and send it
  as a header, and must send a loopback `Host` header. Requests with a foreign
  `Host`, `Origin`, or duplicate Host headers are rejected.
- **`init --adopt` is stricter.** It now refuses to adopt a directory that
  already contains a `.nexusos` entry (or where `.nexusos` is a symlink or
  plain file). Point it at a clean directory.
- **Root-level Markdown is now indexed.** If you previously relied on root
  files being ignored, add them to your exclude config instead.
- **No configuration-file changes required.** Existing `nexusos.toml` files and
  `NEXUSOS_*` env overrides keep working; invalid env value types now fail fast
  with a clear error naming the variable.

## Known issues

Not implemented in this release (unchanged from alpha.1):

- Embeddings / vector database
- Source mutation through MCP (the MCP server is read-only by design)
- Cloud features, OAuth, multi-user

Accepted residual hardening items from the security review (LOW/INFO; tracked
for future releases):

- TOCTOU symlink-swap window between discovery and read within an untrusted
  workspace (F-03)
- Relative `NEXUSOS_DENY_PATHS` entries resolve against the current working
  directory (F-05)
- Unbounded response limits on the serve HTTP transport (F-06)
- A dead symlink-escape helper remains in `core/path_safety.py` (F-07)
- `serve --host` may still bind a non-loopback interface, with a loud warning
  (F-08)

## Verification

- **414 tests passing** (up from 363 at alpha.1 re-verification), zero failures
- `ruff check` clean, `ruff format --check` clean, `mypy` strict clean
- Regression tests added for every fix, including real-CLI (L4) reproductions
  for F1, F2, F-01, F-02, F3, and F4/F5/F7
- Commits in this release: `db75fb1`, `12d674d`, `8687fbf`, `487c60f`,
  `10cea9c`, `c7a40ec`, `62b00f5`

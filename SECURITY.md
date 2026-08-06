# Security Policy

NexusOS is currently pre-release software. Security reports are welcome, but the project
has not yet declared a stable support window.

## Supported versions

| Version | Status |
|---|---|
| `0.1.0-rc.1` | Current release candidate, receiving security fixes |
| `0.1.0-alpha.3` | Previous prerelease, receiving security fixes until `v0.1.0` |
| Earlier commits and unreleased snapshots | Best effort only |

The policy will be updated when `v0.1.0` is released.

## Supported deployment boundary

NexusOS v0.1 is designed for a **local, single-user workspace controlled by the
operator**. It is not an internet-facing multi-user service and does not provide a full
authentication or authorization system.

Core workflows require no network access. MCP stdio runs as a local subprocess. The local
inspection API and MCP Streamable HTTP bind to loopback by default.

The two HTTP surfaces have different security contracts:

- the **inspection API and UI** validate Host, reject foreign Origin values, and require a
  per-process `X-NexusOS-Token` for `/api/*`
- the **MCP Streamable HTTP endpoint** is an unauthenticated JSON-RPC endpoint that
  includes the derived-state `index` tool

For the inspection API, a non-loopback bind warns and proceeds (the token is the access
control). For MCP Streamable HTTP, a non-loopback bind is **refused** unless the operator
explicitly opts in with `--allow-non-loopback` or `NEXUSOS_ALLOW_NON_LOOPBACK=1` (F-08
resolved). Neither HTTP surface should be exposed to an untrusted network without an
external security layer appropriate to the deployment.

## Security invariants

The v0.1 contract is intended to preserve these invariants:

1. Retrieval, linting, status, and MCP read tools do not mutate source documents.
2. Index writes are limited to derived state inside `.nexusos/`.
3. Workspace operations reject dangerous roots and paths outside the workspace boundary.
4. Nested workspaces are refused.
5. Symlink behavior is explicit and constrained by workspace policy. Escaping symlinks
   are detected at index time and surfaced by `nexusos doctor` and `nexusos init --adopt`
   (F-07 resolved).
6. Critical state writes use atomic replacement with unpredictable temporary names.
7. Index writes are transactional and protected by an exclusive writer lock.
8. Configuration display does not expose secret-pattern environment variables.
9. The local inspection API validates Host, rejects foreign Origin values, requires a
   per-process `X-NexusOS-Token` for `/api/*`, and disables caching for the injected UI.
10. The core retrieval path is deterministic and does not invoke an LLM or remote service.
11. Source files are re-validated against the workspace boundary immediately before the
    indexer reads them, closing the scan-to-read TOCTOU window (F-03 resolved).
12. Result limits (search/browse/recent/context) and `[search]` configuration values are
    range-validated consistently across the CLI, JSON, config, and MCP surfaces (F-06
    resolved).
13. Derived state files are owner-only: the index database (and its WAL/SHM siblings) and
    the index lock are created `0600`, matching `workspace.json` (F-09/F-12 resolved).
14. The API token is embedded in the served UI page only for loopback binds; on a
    non-loopback bind the unauthenticated root page never contains the token, so the token
    remains an actual access control for `/api/*` (F-10 resolved).
15. Search terms are length-bounded consistently on the CLI and MCP surfaces so a single
    caller cannot force unbounded FTS work (F-13 resolved).

Security tests should prove these invariants using synthetic workspaces.

## Denied paths

Set `NEXUSOS_DENY_PATHS` with the operating system path separator:

```bash
# Linux and macOS
export NEXUSOS_DENY_PATHS="/home/private:/etc/sensitive"

# Windows PowerShell
$env:NEXUSOS_DENY_PATHS = "C:\Private;D:\Secrets"
```

Entries must be **absolute paths** (after tilde expansion). Relative entries are
non-deterministic — they would resolve against the process working directory and
could silently miss the location the operator intended to protect — so they are
ignored with a one-time warning (F-05 resolved).

Built-in forbidden prefixes include sensitive operating-system locations such as `/etc`,
`/proc`, `/sys`, `/dev`, `/boot`, `/run`, `C:\Windows`, and `C:\Program Files`.
Workspace roots at `/` and the current user home directory are refused.

## Out of scope for v0.1

The following protections are not provided by the current release line:

- multi-user authentication or authorization
- hosted-service tenant isolation
- encrypted synchronization
- remote secret management
- internet-facing TLS termination
- source-document write approvals
- sandboxing of the local operating-system account running NexusOS

Do not deploy NexusOS as though these controls exist.

## Reporting a vulnerability

Do not open a public issue with vulnerability details. The repository's
**private reporting path** is GitHub's private advisory flow:

1. Open https://github.com/asimons81/nexusos/security/advisories/new (or
   **Security → Report a vulnerability** on the repository page). This creates
   a private advisory that is only visible to the maintainer until it is
   published.
2. If the private advisory flow is unavailable for any reason, contact the
   maintainer directly through the GitHub profile
   (https://github.com/asimons81) and request a secure intake path **before**
   sharing technical details.
3. Include the affected version or commit, operating system, reproduction
   steps, impact, and any proposed mitigation.
4. Avoid accessing data you do not own and use synthetic workspaces whenever
   possible.

A dedicated published security contact is a release-readiness requirement in
roadmap item `A3-07`; the private advisory flow above is that contact path.

## Disclosure expectations

Please allow reasonable time to reproduce, fix, test, and release a correction before
public disclosure. The project will credit reporters who want attribution, unless legal
or safety constraints prevent it.
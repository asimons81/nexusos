# Security Policy

NexusOS is currently pre-release software. Security reports are welcome, but the project
has not yet declared a stable support window.

## Supported versions

| Version | Status |
|---|---|
| `0.1.0-alpha.2` | Current prerelease, receiving security fixes |
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

A user may explicitly request a non-loopback bind. That is an operator override of the
supported default. Neither HTTP surface should be exposed to an untrusted network without
an external security layer appropriate to the deployment.

## Security invariants

The v0.1 contract is intended to preserve these invariants:

1. Retrieval, linting, status, and MCP read tools do not mutate source documents.
2. Index writes are limited to derived state inside `.nexusos/`.
3. Workspace operations reject dangerous roots and paths outside the workspace boundary.
4. Nested workspaces are refused.
5. Symlink behavior is explicit and constrained by workspace policy.
6. Critical state writes use atomic replacement with unpredictable temporary names.
7. Index writes are transactional and protected by an exclusive writer lock.
8. Configuration display does not expose secret-pattern environment variables.
9. The local inspection API validates Host, rejects foreign Origin values, requires a
   per-process `X-NexusOS-Token` for `/api/*`, and disables caching for the injected UI.
10. The core retrieval path is deterministic and does not invoke an LLM or remote service.

Security tests should prove these invariants using synthetic workspaces.

## Denied paths

Set `NEXUSOS_DENY_PATHS` with the operating system path separator:

```bash
# Linux and macOS
export NEXUSOS_DENY_PATHS="/home/private:/etc/sensitive"

# Windows PowerShell
$env:NEXUSOS_DENY_PATHS = "C:\Private;D:\Secrets"
```

Built-in forbidden prefixes include sensitive operating-system locations such as `/etc`,
`/proc`, `/sys`, `/dev`, `/boot`, `/run`, `C:\Windows`, and `C:\Program Files`.
Workspace roots at `/` and the current user home directory are refused.

Use absolute entries in `NEXUSOS_DENY_PATHS` during the current alpha. Relative entries
are part of the hardening work tracked as `F-05`.

## Known alpha findings

The following items are documented, accepted prerelease limitations. They remain visible
until fixed or explicitly deferred through the release process.

### F-03: path-safety TOCTOU window

Some path-safety checks are check-then-use operations. A concurrent hostile process that
can replace filesystem entries between validation and access may race those checks.

The current supported boundary assumes a local workspace without an untrusted process
actively racing NexusOS. Closing or formally deferring this finding is required by
roadmap task `A3-01`.

### F-05: relative deny paths use the current working directory

Relative entries in `NEXUSOS_DENY_PATHS` are resolved against the process working
directory rather than the workspace root. Use absolute deny paths during the alpha.

### F-06: search configuration values are not range-clamped

`search_max_results` and `search_snippet_length` accept integer values without complete
range validation. Invalid values may fail at runtime. Do not treat untrusted environment
or configuration input as safe until the hardening task is complete.

### F-07: unused symlink defense helper

`check_symlink_escape` is currently defense-in-depth code rather than a consistently
invoked public-path guard. Active indexing behavior is controlled by the configured
symlink policy. The helper must be integrated into real paths or removed to avoid a false
sense of protection.

### F-08: non-loopback bind is operator-selected

NexusOS warns and proceeds when the operator explicitly binds a server to a non-loopback
host.

For the inspection API, Host, Origin, and token checks remain active, but they are not a
substitute for TLS, identity, authorization, network policy, and a production reverse
proxy.

For MCP Streamable HTTP, the endpoint is unauthenticated and includes the `index` tool.
Do not expose it directly to an untrusted network.

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

Do not open a public issue with vulnerability details.

1. Use GitHub's private **Report a vulnerability** flow for this repository when it is
   available.
2. If the private advisory flow is unavailable, contact the maintainer through a private
   channel and request a secure intake path before sharing technical details.
3. Include the affected version or commit, operating system, reproduction steps, impact,
   and any proposed mitigation.
4. Avoid accessing data you do not own and use synthetic workspaces whenever possible.

A dedicated published security contact is a release-readiness requirement in roadmap
item `A3-07`.

## Disclosure expectations

Please allow reasonable time to reproduce, fix, test, and release a correction before
public disclosure. The project will credit reporters who want attribution, unless legal
or safety constraints prevent it.
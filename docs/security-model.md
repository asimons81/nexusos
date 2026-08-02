# Security Model

## Threat Model

NexusOS is a **local, read-only** memory kernel. Attack surface:

- Malicious symlinks escaping the workspace
- Path traversal in workspace initialization
- Denied-path circumvention
- Source document mutation
- Secret leakage in configuration display

## Defenses

| Threat | Mitigation |
|--------|-----------|
| Symlink escape | `check_symlink_escape()` resolves all symlinks, rejects external targets |
| Path traversal | `validate_within_workspace()` enforces resolved-path boundary |
| Denied paths | `NEXUSOS_DENY_PATHS` + built-in forbidden prefixes |
| Source mutation | Read-only contract; integration tests verify byte-for-byte |
| Secret leakage | Secret-pattern env vars excluded from `--effective` display |
| Nested workspaces | Ancestor + descendant checks on init |
| Root/home init | Hard refused |
| Index DB outside workspace | `IndexKernel` validates the database path via `validate_within_workspace()` before opening |
| Index writer contention | Exclusive-writer lock (`.nexusos/index.lock`); stale locks from dead processes are reclaimed |
| Corrupt/foreign index DB | Schema versioned via `PRAGMA user_version`; incompatible or foreign-workspace DBs rejected with typed errors |

The index database is disposable derived state under `.nexusos/`; read-only commands (`doctor`, `status`) never create it.

## Isolation from Private Nexus

This project shares a design philosophy with a private system but is completely isolated:

- Different namespace (`nexusos` vs private)
- Different CLI, package, env vars, state directory
- No shared code
- No imports or references to private paths
- Tests use synthetic data only

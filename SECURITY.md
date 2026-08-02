# Security

## Safety Guarantees

NexusOS is designed as a **read-only memory kernel**. For v0.1, the system:

1. **Never modifies source documents** outside `.nexusos/`
2. **Blocks dangerous filesystem locations** via `NEXUSOS_DENY_PATHS` and built-in forbidden prefixes
3. **Detects symlink escapes** out of the workspace
4. **Prevents nested workspaces** (no workspaces inside workspaces)
5. **Uses atomic writes** for critical state files
6. **Never requires network access** for core functions
7. **Exposes no secrets** in configuration display
8. **Restricts the local dev server** — `nexusos serve` only honors loopback
   `Host` headers (DNS-rebinding defense), requires a per-process
   `X-NexusOS-Token` for `/api/*` reads, and warns loudly when bound to a
   non-loopback host

## Denied Paths

Set `NEXUSOS_DENY_PATHS` using your OS path separator:

```bash
# Linux/macOS
export NEXUSOS_DENY_PATHS="/home/private:/etc/sensitive"

# Windows
set NEXUSOS_DENY_PATHS=C:\Private;D:\Secrets
```

Built-in forbidden prefixes: `/etc`, `/proc`, `/sys`, `/dev`, `/boot`, `/run`, `C:\Windows`, `C:\Program Files`.

Workspace roots at `/` (root) and `$HOME` are always refused.

## Report a Vulnerability

Please report security issues privately. Do not file public issues.

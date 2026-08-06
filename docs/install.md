# Installing NexusOS

NexusOS is a local-first knowledge index for Markdown vaults. This guide covers
supported environments, dependencies, installation, upgrades, and how to use
the verified release artifacts.

**Current release:** `v0.1.0-alpha.3` (runtime version `0.1.0-alpha.3`,
package version `0.1.0a3`)

> [!IMPORTANT]
> NexusOS is pre-release software. The `v0.1` core feature scope is implemented,
> and release hardening is complete for this prerelease. See
> [ROADMAP.md](../ROADMAP.md) and the
> [v0.1 release notes](releases/v0.1.md) before deploying it somewhere
> important.

---

## Supported environments

| Environment | Status |
|---|---|
| Linux (Arch, KDE desktop) | **Verified** — clean-install smoke, full test gate (435 passed, 1 skipped), artifact checksums |
| Linux (QEMU guest, clean machine) | **Verified** — clean-environment install/upgrade path used for release validation |
| macOS | CI-tested (unit + security suites on 3.11/3.12/3.13); clean-install validation pending at RC-02 |
| Windows | CI-tested (unit + security suites on 3.11/3.12/3.13); clean-install validation pending at RC-02 |
| Python | 3.11 / 3.12 / 3.13 (`requires-python >=3.11`) |

The verified release artifacts were built and smoke-tested on a Linux host
(Arch, GEEKOM A9 Max) with Python 3.11 (wheel) and Python 3.12 (sdist), plus
a clean Linux/QEMU environment for the documented install path. macOS and
Windows clean-install validation is tracked by the A3-02 matrix and RC-02
roadmap tasks.

NexusOS targets **local, single-user workspaces**. Core workflows need no
network access. See [SECURITY.md](../SECURITY.md) for the supported deployment
boundary.

## Dependencies

Runtime:

- Python >= 3.11
- `pydantic>=2.0`
- `typer>=0.12`
- `rich>=13.0`
- `pyyaml>=6.0`
- `mcp>=2.0.0`
- SQLite with FTS5 (Python's built-in `sqlite3`; `nexusos doctor` checks
  availability)

Recommended tooling:

- `uv` for source installs and development (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

Development-only:

- `pytest>=8.0`, `pytest-cov>=5.0`, `ruff>=0.1`, `mypy>=1.8`
- `build`, `twine` for artifact builds

## Install NexusOS

NexusOS is not yet published to PyPI (tracked by RC-01). Install from a source
checkout or from the verified release artifacts.

### Option A — source checkout (recommended for alpha users)

```bash
git clone https://github.com/asimons81/nexusos.git
cd nexusos
uv sync

uv run nexusos version        # => nexusos 0.1.0-alpha.3
```

`uv run` uses the project virtualenv. If you prefer a global install from the
checkout:

```bash
uv pip install --system .
```

### Option B — verified wheel artifact

Download `nexusos-0.1.0a3-py3-none-any.whl` from the release artifacts (or
build it per [docs/releasing.md](releasing.md)), then:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install nexusos-0.1.0a3-py3-none-any.whl

nexusos version                  # => nexusos 0.1.0-alpha.3
```

### Option C — verified sdist artifact

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install nexusos-0.1.0a3.tar.gz

nexusos version                  # => nexusos 0.1.0-alpha.3
```

### Verify the install

```bash
nexusos version
nexusos --help
nexusos demo                     # scripted end-to-end walkthrough in a temp vault
nexusos init --template starter ./my-workspace
nexusos doctor --workspace ./my-workspace
nexusos index --workspace ./my-workspace
nexusos status --workspace ./my-workspace
nexusos search "your term" --workspace ./my-workspace
```

All commands above were verified against the `0.1.0a3` wheel and sdist in
clean environments (see [docs/release/v0.1.0-manifest.md](release/v0.1.0-manifest.md)).

## Upgrade

### From an earlier alpha (alpha.1 → alpha.2 / current)

1. Install the new version using one of the options above.
2. Run `nexusos index` once on each existing workspace. This applies the
   schema v1 → v2 migration and picks up warning-detail persistence.

Read-only commands never migrate the database. If they hit an older schema
they print a clear "run `nexusos index`" message instead of failing
cryptically.

### Behavior changes to expect

- **`nexusos serve` HTTP API callers need a token.** The server prints a
  per-process `X-NexusOS-Token` at startup and injects it into the bundled UI.
  Any direct caller of `/api/*` must send that token as a header and a
  loopback `Host` header. Foreign Hosts, Origins, and duplicate Host headers
  are rejected.
- **`init --adopt` is stricter.** It refuses to adopt a directory that already
  contains a `.nexusos` entry, or where `.nexusos` is a symlink or plain file.
- **Root-level Markdown is now indexed.** If you relied on root files being
  ignored, add them to your exclude config.
- **Result limits are enforced.** `search`, `browse`, `recent`, and `context`
  limits are range-validated across CLI, config, JSON, and MCP.
- **Deny paths must be absolute.** Relative `NEXUSOS_DENY_PATHS` entries are
  ignored with a warning; only absolute entries match.
- **Non-loopback MCP bind is refused** unless you pass
  `--allow-non-loopback` or set `NEXUSOS_ALLOW_NON_LOOPBACK=1`. The MCP
  Streamable HTTP endpoint is unauthenticated and includes the `index` tool.
- **No configuration-file changes required.** Existing `nexusos.toml` files
  and `NEXUSOS_*` env overrides keep working; invalid env value types now fail
  fast with a clear error.

### Downgrade

Schema downgrades are not implemented. If you must move backward, delete the
derived state (`.nexusos/`) and re-`init`, or keep a workspace on the older
version. Source files are never touched by the index.

## Using the verified release artifacts

The authoritative artifact manifest is
[docs/release/v0.1.0-manifest.md](release/v0.1.0-manifest.md) — it records
SHA-256 checksums, the build commit, repository gate results, and clean
environment smoke tests.

```bash
# Verify checksums after downloading
sha256sum -c SHA256SUMS          # or compare against the manifest table
```

Artifacts (v0.1.0-alpha.3, build commit `ed46376`):

- `nexusos-0.1.0a3-py3-none-any.whl`
- `nexusos-0.1.0a3.tar.gz`

## Uninstall

```bash
# From a virtualenv
pip uninstall nexusos
```

NexusOS stores workspace state inside each workspace's `.nexusos/` directory.
Removing the package does not touch your source files; delete `.nexusos/` per
workspace if you want to reclaim the derived state.

## Troubleshooting

- **`pydantic_core` import error in a shared environment:** if your global
  Python path points at a Hermes/agent venv, run commands with
  `env -u PYTHONPATH` (or use a fresh venv). This is environment noise, not a
  package defect.
- **`doctor` reports `sqlite_fts5` missing:** your Python build lacks the FTS5
  extension. Use a Python distribution that bundles FTS5 (standard CPython
  builds do).
- **`status` says "run `nexusos index`":** the workspace database schema is
  older than the installed version. Run `nexusos index --workspace <path>`.
- **`lint` reports findings on a fresh starter workspace:** the starter
  template documents `[[page-name]]` wiki-link syntax as an example, and the
  linter correctly flags it as unresolved. This is expected template behavior,
  not a defect.

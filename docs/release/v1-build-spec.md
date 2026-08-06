# NexusOS v1 Build Spec

> **Status:** executable build-and-release contract for the first stable NexusOS
> release. Defines how we get from `v0.1.0-alpha.3` (shipped) to stable.
>
> **What "v1" means here:** the first stable release of NexusOS, which is
> versioned `v0.1.0` per [ROADMAP.md](../../ROADMAP.md). The post-v0.1 direction
> (embeddings, ingestion connectors, guarded source writes, Studio, fleet
> memory, sync, hosted MCP) is explicitly **out of scope** for this spec and for
> the v0.1 release train.
>
> **Related documents** (this spec sequences them; it does not replace them):
>
> | Document | Role |
> |---|---|
> | [ROADMAP.md](../../ROADMAP.md) | Source of truth for release tasks, dependencies, gates |
> | [v0.1-checklist.md](v0.1-checklist.md) | Audit checklist: roadmap → card mapping, status |
> | [v0.1.0-manifest.md](v0.1.0-manifest.md) | Evidence ledger: artifacts, hashes, clean installs, MCP, upgrades |
> | [../releasing.md](../releasing.md) | Release procedure: roles, version scheme, publish, rollback |

---

## 1. Release identity

| Field | `v0.1.0-alpha.3` (shipped) | `v0.1.0-rc.1` (next) | `v0.1.0` (target) |
|---|---|---|---|
| `pyproject.toml` version | `0.1.0a3` | `0.1.0rc1` | `0.1.0` |
| Runtime / docs version | `0.1.0-alpha.3` | `0.1.0-rc.1` | `0.1.0` |
| Git tag | `v0.1.0-alpha.3` | `v0.1.0-rc.1` | `v0.1.0` |
| Release type | GitHub prerelease | GitHub prerelease + TestPyPI prerelease | GitHub release + PyPI final |

**Version agreement is a gate.** Before any tag, verify all of the following
agree with the intended version (see `docs/releasing.md` §2 and the
`python-package-release` checklist — current-version references only, never
changelog history):

- `pyproject.toml` `[project] version`
- `src/nexusos/__init__.py` `__version__`
- `README.md` version badge + status text
- `CHANGELOG.md` top entry
- `ROADMAP.md` current-release header
- `docs/releases/v0.1.md` status line
- `docs/release/v0.1-checklist.md` header
- release tag and release title

## 2. Build environment contract

| Dimension | Requirement |
|---|---|
| Python | `>=3.11`; CI matrix on 3.11 / 3.12 / 3.13 |
| OS | Linux (build host: Arch, GEEKOM A9 Max), macOS, Windows |
| Package manager | `uv` (locked via `uv.lock`) |
| Build backend | hatchling (`src/` layout) |
| Build tooling | `python -m build`, `twine` (check only) |
| Quality gates | ruff (lint + format), mypy strict, pytest + coverage |
| Artifacts | sdist (`nexusos-<version>.tar.gz`) + wheel (`nexusos-<version>-py3-none-any.whl`) |

**Environment pitfall (GEEKOM host):** the global Hermes venv on the build host
can break `pydantic_core` when `PYTHONPATH` leaks into the project venv. Run all
local gates with `env -u PYTHONPATH`. This is environment noise, not a package
defect (recorded in the manifest §3).

## 3. Artifact contract

The shipped artifacts must satisfy (inspection recipe in `docs/releasing.md` §4
and the `python-package-release` skill §4):

- **Wheel:** `src/nexusos` runtime modules, console entry point
  (`nexusos = nexusos.cli.main:main`), bundled UI (`nexusos/ui/index.html`),
  correct `Version` / `License` / `Requires-Python` metadata. No `.db`,
  `__pycache__`, `.sqlite`, `.pyc`, `.env`, or absolute paths.
- **Sdist:** `src/nexusos/**`, `src/nexusos/ui/**`, README, LICENSE, CHANGELOG,
  ROADMAP, SECURITY, CONTRIBUTING, AGENTS, `docs/`, `examples/` (declared in
  `pyproject.toml` `[tool.hatch.build.targets.sdist]`).
- **Checksums:** SHA-256 recorded in `docs/release/v0.1.0-manifest.md` and a
  `SHA256SUMS` file attached to the GitHub release. Archive hashes are **not**
  reproducible across builds (metadata timestamps); record the authoritative
  hashes from the final build of the tagged commit.
- **`twine check dist/*` must pass.**

## 4. Verification gates (exact commands)

### 4.1 Repository gate (every stage, on the frozen commit, clean tree)

```bash
env -u PYTHONPATH
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q --cov=nexusos
uv run nexusos version
```

Baseline at alpha.3 (2026-08-05): **614 passed, 1 skipped**, ruff/format/mypy
clean, coverage 84–85% measured with enforced floor **80%**
(`fail_under = 80` in `pyproject.toml`). CI additionally enforces security-module
floors: `core/path_safety.py` ≥85, `indexing/lock.py` ≥75,
`services/serve_service.py` ≥75, `mcp/server.py` ≥65, `mcp/__main__.py` ≥90.

### 4.2 Build and artifact check

```bash
git status --short        # clean tree required
rm -rf dist build
uv run --with build python -m build
uv run --with twine twine check dist/*
```

Then inspect wheel + sdist per §3 and record hashes.

### 4.3 Clean-environment smoke (wheel, outside the repo)

```bash
uv venv /tmp/nxo-smoke
uv pip install --python /tmp/nxo-smoke/bin/python dist/nexusos-<version>-py3-none-any.whl
# then, with the venv active:
nexusos version
nexusos --help
nexusos demo
nexusos init --template starter /tmp/nxo-ws
nexusos doctor --workspace /tmp/nxo-ws
nexusos index --workspace /tmp/nxo-ws
nexusos status --workspace /tmp/nxo-ws
nexusos search nexus --workspace /tmp/nxo-ws
nexusos lint --workspace /tmp/nxo-ws
```

Repeat for the sdist, and repeat both on **Linux, macOS, and Windows** before
stable (RC-02). As of alpha.3 only Linux clean-install evidence exists
(manifest §5); macOS/Windows clean installs are the open RC-02 item.

### 4.4 MCP validation (from the installed artifact)

stdio:

```bash
nexusos mcp --workspace /tmp/nxo-ws
```

Streamable HTTP:

```bash
nexusos serve --transport streamable-http --workspace /tmp/nxo-ws --port <p>
```

Record evidence for: initialize + shutdown, tool discovery (8 tools: `browse,
context, index, links, read, recent, search, status`), strict-schema rejection
of extra args, `status` / `search` / `read` / `context` / `index` behavior,
missing/stale index behavior, typed tool errors, and byte-for-byte source
immutability after retrieval calls. Representative client validation is required
at RC (RC-03); protocol behavior is the gate, not every client config format.

### 4.5 Upgrade and schema validation (RC-04 and stable)

1. Open a workspace from the previous published prerelease (alpha.2 or rc.1 as
   applicable) with the candidate.
2. Verify supported schema migration (`PRAGMA user_version` 1 → 2; read-only
   commands never migrate).
3. Verify clear refusal of unsupported future schemas on both read-only and
   index paths.
4. Delete derived state (`.nexusos/index.sqlite3` + WAL) and rebuild; source
   bytes must be byte-for-byte identical.
5. Verify full `.nexusos/` deletion + `nexusos init --adopt` recovery.
6. Document downgrade expectations: schema downgrades are not implemented; do
   not imply a safe downgrade path.

## 5. Stage gates

### Stage 0 — `v0.1.0-alpha.3` (DONE)

Shipped 2026-08-05: tag `v0.1.0-alpha.3` @ `ca391a5` (== origin/main), GitHub
prerelease with wheel + sdist + SHA256SUMS. A3-01..A3-07 complete; RC-03/RC-04
evidence in the manifest. Roadmap, changelog, README, package version, runtime
version agree.

### Stage 1 — `v0.1.0-rc.1` (release candidate)

**Entry gate (all true):**
- All A3 tasks complete (done) and no release-blocking defect open
- RC-01..RC-05 acceptance criteria from ROADMAP.md defined and pending evidence

**Build sequence:**

1. Freeze the intended base commit on `main`; create `release/v0.1.0-rc.1`.
2. Bump versions to `0.1.0rc1` / `0.1.0-rc.1` across every source in §1;
   update changelog, roadmap status, README, `docs/releases/v0.1.md`, checklist
   header. Commit as `Prepare v0.1.0-rc.1 release`.
3. Push; wait for the full CI 3×3 matrix + contract suite to be green.
4. Run the repository gate (§4.1), build + artifact check (§4.2), and Linux
   clean-environment smoke (§4.3) on the frozen commit.
5. Run MCP validation (§4.4) and upgrade/schema validation (§4.5) from the
   installed artifact; record evidence in the manifest.
6. Clean-machine validation on macOS and Windows (RC-02) — CI full-suite green
   is not a substitute for clean-install smoke; record exact environments.
7. Publish the prerelease to the package index (TestPyPI or PyPI prerelease,
   per RC-01) using the maintainer's secure credentials only. Verify install
   from the public index and rerun minimal smoke.
8. Create annotated tag `v0.1.0-rc.1` at the exact verified commit; push tag.
9. Create the GitHub prerelease with notes + sdist + wheel + SHA256SUMS.
10. Update the manifest (§7) and checklist; mark RC-01/RC-02 complete.

**Exit condition:** RC gate complete — RC-01..RC-05 pass, no release-blocking
defect open, documentation matches the installed package, clean-machine evidence
attached.

### Stage 2 — `v0.1.0` (stable)

**Entry gate (all true):**
- `v0.1.0-rc.1` shipped and RC gate complete
- RC-05 public contract freeze in effect: since RC-05 began, no changes to CLI
  commands/options, config keys/defaults, MCP tool names/schemas, JSON shapes,
  or documented exit codes except release-blocking fixes
- No release-blocking defect open

**Build sequence:** same shape as Stage 1 (freeze → `Prepare v0.1.0 release` →
gate → build → 3-OS clean install → MCP smoke → upgrade/rebuild → final
security review → changelog/notes complete) **plus**:

1. Publish `0.1.0` to PyPI (maintainer credentials / trusted publishing; never
   a static token or `twine upload` for first publication).
2. Create the **verified/signed** annotated tag `v0.1.0` at the exact verified
   commit (SSH signing; allowed-signers file `.github/release-signers`; CI step
   `git tag -v` before release; push only the tag).
3. Create the GitHub release (non-prerelease) with notes + sdist + wheel +
   SHA256SUMS.
4. Update README badges/install instructions to stable; verify from a clean
   checkout.
5. Record the final evidence packet (§7) and close the board.

**Definition of stable** (ROADMAP.md): a release is stable when the published
artifact, public contracts, documentation, and evidence all agree — not because
the feature checklist is full.

## 6. Authority and human gates

- **Release owner (`default` profile):** owns the build sequence, verification,
  evidence, and board closeout. A coding agent may prepare and verify release
  work.
- **Maintainer (Tony):** holds publication credentials and final release
  authority. Required at:
  - PyPI/TestPyPI publish (RC-01 and stable) — no credentials exist in the
    environment; this is the maintainer-only step
  - Stable signed-tag creation (signing key on the GEEKOM host)
  - Any roadmap or stable-API change; public repo flip decisions
- Agents must **not** publish to PyPI, change stable contracts, delete/recreate
  published tags, or force-push release history without explicit approval.

## 7. Evidence obligations

| Gate | File to update | Contents |
|---|---|---|
| Every build | `docs/release/v0.1.0-manifest.md` | Release identity, build commit, artifact hashes, gate results, clean installs, MCP, upgrade validation, reproduce path |
| Every stage | `docs/release/v0.1-checklist.md` | Status columns for roadmap → card mapping |
| Every stage | `docs/releases/v0.1.md` + `CHANGELOG.md` | Release notes, known limitations, verification summary |
| Every release | GitHub release assets | sdist + wheel + `SHA256SUMS` |
| Every release | board | Completion cards with evidence, run URLs, test totals |

## 8. Failed release and rollback

- Treat every publication as permanent; package indexes may not permit replacing
  an artifact.
- If publication succeeds but validation fails: do **not** reuse the published
  version number, document the defect immediately, prepare a new patch or
  prerelease version, and mark the bad release clearly in release notes.
- Never delete, recreate, or force-push a published tag; cut a patch release
  instead.
- Preserve evidence needed to diagnose a failure; do not "fix" the checklist to
  make a failed gate pass.

## 9. One-page sequence

```text
alpha.3 (DONE: tag v0.1.0-alpha.3 @ ca391a5, prerelease live)
  │  all A3 complete, RC-03/RC-04 evidence in manifest
  ▼
RC-01..RC-05 build (v0.1.0-rc.1)
  freeze commit → release/v0.1.0-rc.1 → version bump (8 sources agree)
  → CI 3×3 green → repo gate → build+twine → Linux clean smoke
  → MCP + upgrade/schema validation → macOS/Windows clean installs (RC-02)
  → publish prerelease → public-index install smoke → signed tag → GitHub prerelease
  │
  ▼
Stable build (v0.1.0)
  RC gate complete + contract freeze in effect → version bump → CI green
  → build+twine → 3-OS clean install → MCP smoke → upgrade/rebuild
  → final security review → PyPI publish (maintainer) → signed tag v0.1.0
  → GitHub release → README stable → evidence packet → board closeout
```

*Every gate above requires the repository gate (§4.1), artifact check (§4.2),
and evidence (§7) before the next step. Never report "done" on code generation
or a narrow test subset.*

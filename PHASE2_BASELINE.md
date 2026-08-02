# PHASE2_BASELINE.md

**Task:** t_f6df481f — Audit NexusOS codebase and capture baseline constraints
**Date:** 2026-08-02
**Auditor:** Hermes (default profile)
**Repo:** /home/tony/projects/nexusOS (no git repo initialized; plain directory)
**Upstream consumer:** t_23be9a75 (v0.1.0-alpha.2 Indexing Kernel)

This note is the baseline contract for Phase 2 work. Every constraint below was
verified by reading the repository and running the full toolchain on this machine.

---

## 0. Baseline verification results (recorded 2026-08-02)

Environment: Python 3.12.13 (uv-managed venv `.venv/`), uv 0.11.29, SQLite FTS5 available.

| Check | Command | Result |
|---|---|---|
| Sync | `uv sync` | OK — 27 packages resolved, 25 checked |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 35 files already formatted |
| Types | `uv run mypy src` | Success — no issues in 12 source files |
| Tests | `uv run pytest -q` | **80 passed, 0 failed** |
| Version | `uv run nexusos version` | `nexusos 0.1.0-alpha.1` |
| Smoke | init + doctor + config show on synthetic workspace | All healthy |

Test breakdown (80 total):
- tests/security/test_isolation.py — 8
- tests/unit/test_config.py — 7
- tests/unit/test_doctor.py — 7
- tests/unit/test_errors.py — 4
- tests/unit/test_init.py — 21
- tests/unit/test_models.py — 11
- tests/unit/test_path_safety.py — 22

CI (`.github/workflows/ci.yml`): matrix ubuntu/macos/windows × python 3.11/3.12/3.13,
runs lint, format check, mypy, `pytest tests/unit/`, `pytest tests/security/`, smoke `nexusos version`.

**Phase 2 must keep all 80 tests passing.**

---

## 1. Current public command names, behavior, and output contracts

Typer app in `src/nexusos/cli/main.py`; entry point `nexusos = "nexusos.cli.main:app"`.
`no_args_is_help=True`; bare `nexusos` prints help and exits 0.

### 1.1 `nexusos version`
- Output: `nexusos 0.1.0-alpha.1`
- Exit: 0. No other behavior.

### 1.2 `nexusos init PATH [--template/-t blank|starter] [--dry-run] [--adopt]`
- Default template `starter`; template options: `blank`, `starter` (anything else → TemplateError, exit 2).
- **Dry run:** prints `Dry run for: <target>`, `Would create:`, one line per entry
  `  [DIR] <rel>` or `  [FILE] <rel>` (sorted), then `N entries (no changes made)`. Creates nothing.
- **Real run:** prints `Initialized workspace at <resolved target>`, `  Template: <template>`,
  `  Created: <N> entries`. Creates directories, `.nexusos/workspace.json` (atomic), `nexusos.toml`,
  `README.md`, and for starter also `SCHEMA.md`.
- Errors printed to stderr as `Error: <message>`; exit codes: safety rejections = 2 (see §2).
- `--adopt` permits initializing into a non-empty directory; existing files are preserved
  (never overwritten — `_write_if_missing`).

### 1.3 `nexusos doctor [--workspace/-w PATH] [--json]`
- Default path: cwd. Runs 2 always-on checks + up to 9 workspace-dependent checks.
- Check IDs (contract): `python_version`, `sqlite_fts5`, `workspace_detection`, `workspace_id`,
  `root_boundary`, `denied_paths`, `state_dir_writable`, `config_parsing`, `template_files`,
  `nested_workspaces`, `source_dirs`.
- Human output: Rich table titled "NexusOS Doctor" with Check/Status/Message columns,
  status icons `✓ PASS` / `⚠ WARN` / `✗ FAIL`, footer `Passed: N  Warnings: N  Failures: N`,
  then `Workspace is healthy.` (green) or `Workspace has blocking issues.` (red).
- `--json`: `json.dumps(report.model_dump(mode="json"), indent=2)` — keys:
  `workspace_root`, `checks[]` (check/status/message/detail), `passed`, `warnings`, `failures`, `healthy`.
- Exit: 0 if `healthy` (failures == 0), 1 otherwise.
- **Doctor must not create `.nexusos/index.sqlite3`** (Phase 2 invariant).

### 1.4 `nexusos config show [--workspace/-w PATH] [--effective/-e] [--json]`
- Action argument defaults to `"show"`; any other value → `Unknown config action: <action>`, exit 1.
- Without `--workspace`: detects workspace from cwd via `find_nearest_workspace_root`;
  none found → `Error: No workspace detected. Run `nexusos init` first.`, exit 1.
- `--effective`: `load_config_effective(ws_root)` (TOML + env overrides, sets `root` to resolved ws).
- Default (no `--effective`): `load_config(config_path, apply_env=False)` (raw TOML, `root` is None).
- `--json`: `json.dumps(nexusos_config.to_safe_dict(), indent=2, default=str)`.
- Human: Rich table "NexusOS Configuration (effective)?" with Key/Value rows, sorted keys,
  lists joined by `, `.
- **Secrets:** env vars matching SECRET/TOKEN/KEY/PASSWORD are excluded from display
  (verified: `NEXUSOS_API_KEY=supersecret123` never appears in `--effective --json` output).

### 1.5 Commands that do NOT exist yet (do not claim them)
`index`, `status`, `search`, `browse`, `read`, `recent`, `links`, `context`, `lint`, `serve`,
`demo` are **not implemented**. Phase 2 adds `index` and `status` only.

### 1.6 Established exit-code contract (current)
- 0 — success / healthy
- 1 — general failure, unhealthy doctor, unknown config action, unexpected error
- 2 — safety-policy rejection / invalid config file: `DeniedPathError`, `RootOrHomeError`,
  `NestedWorkspaceError`, `NonEmptyDirectoryError`, `WorkspaceAlreadyExistsError`,
  `TemplateError`, `ConfigError` (missing/unreadable/invalid TOML)

---

## 2. Safety guarantees and invariants that must not regress

1. **Read-only contract.** Never mutate source documents. Allowed writes only:
   (a) files created by `nexusos init`, (b) derived state inside `.nexusos/`,
   (c) logs/reports explicitly requested. No MCP source-mutation tools in v0.1.
   Phase 2 allowed writes are exactly: `.nexusos/index.sqlite3` and transient lock artifacts.
2. **Denied paths.** `NEXUSOS_DENY_PATHS` (OS path separator split) + built-in
   `FORBIDDEN_PREFIXES`: `/etc`, `/proc`, `/sys`, `/dev`, `/boot`, `/run`, `/var/run`,
   `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`. Deny → `DeniedPathError` exit 2.
3. **Root/home refusal.** Workspace root at `/`, `$HOME`, or `C:\` always refused (exit 2).
4. **Nested workspace prevention.** Ancestor-with-workspace or descendant-with-workspace → error.
5. **Symlink escape detection.** Any symlink resolving outside the workspace root → `SymlinkEscapeError`.
6. **Atomic writes** for `.nexusos/workspace.json` (temp file + rename). Keep this pattern for state.
7. **No secrets in config display.** Secret-pattern env vars never shown.
8. **No network access.** Core functions must not require network.
9. **Namespace isolation.** CLI `nexusos`, package `nexusos`, env `NEXUSOS_*`, state `.nexusos/`,
   config `nexusos.toml`, default DB `.nexusos/index.sqlite3`, doc IDs `nxo_doc_*`,
   chunk IDs `nxo_chk_*`, run IDs `nxo_run_*`, HTTP port 8765, MCP tools `nexusos_*`.
10. **Disposable index.** Deleting the DB and reindexing must fully reconstruct it.
11. **Deterministic search.** SQLite FTS5 only; no LLM in retrieval path (later phases).
12. **No absolute host paths in normal status/JSON output** (Phase 2 requirement).
13. **Integration tests must prove source files remain byte-for-byte unchanged.**
14. **Tests use synthetic fixtures only.** No private paths, domains, or personal data.

---

## 3. Architecture / package boundaries and layering rules

Dependency direction (AGENTS.md + docs/architecture.md):

```
core (errors, models, path_safety, config)
    ↓
workspace (init, identity)
    ↓
services (doctor, future: index, status)
    ↓
cli (Typer + Rich adapter)
```

Phase 2 extends this to (from t_23be9a75 §3):

```
core and configuration
    ↓
workspace safety
    ↓
discovery and parsing
    ↓
indexing and graph construction
    ↓
shared services
    ↓
CLI
```

New package areas: `discovery/` (models, patterns, scanner), `parsing/`
(frontmatter, markdown, plaintext, headings, wikilinks), `indexing/`
(database, migrations, schema, ids, chunker, indexer, graph, lock),
`services/index_service.py`, `services/status_service.py`.

Hard rules:
- **core must not import Typer, Rich, or MCP packages.**
- Parsing must not depend on SQLite; discovery must not parse content;
  indexing may depend on discovery + parsing; services coordinate; CLI depends on services.
- No lower layer imports CLI code. No MCP dependencies. No network. No LLM.
- CLI stays a thin adapter: Typer command → service call → output formatting.
- `from __future__ import annotations` in all modules; Pydantic v2; mypy strict; ruff; 100-char lines.
- Config precedence: built-in defaults < `nexusos.toml` < `NEXUSOS_*` env < CLI flags.

---

## 4. Phase 0 / Phase 1 modules and APIs the indexing kernel must build on

### 4.1 `src/nexusos/core/errors.py`
`NexusOSError(message, *, exit_code=1)` hierarchy. Subclasses: `ConfigError`,
`WorkspaceError` (with `WorkspaceNotFoundError`, `WorkspaceAlreadyExistsError`,
`NestedWorkspaceError`, `DeniedPathError` exit 2, `SymlinkEscapeError`,
`PathSafetyError`, `NonEmptyDirectoryError`, `RootOrHomeError`), `DoctorError`, `TemplateError`.
Phase 2 adds typed errors (§17 of t_23be9a75) as subclasses of `NexusOSError`, reusing exit codes.

### 4.2 `src/nexusos/core/models.py`
- `WorkspaceIdentity` (frozen): `schema_version=1`, `workspace_id` (must start `nxo_ws_`),
  `created_at`, `nexusos_version`. Serialized to `.nexusos/workspace.json`.
- `NexusOSConfig` (`extra="forbid"`): `workspace_name`, `root`, `include_patterns`
  (default `["**/*.md", "**/*.txt"]`), `exclude_patterns` (`.nexusos/**, node_modules/**,
  __pycache__/**, .git/**, .direnv/**`), `collection_mappings: dict[str,str]`,
  `max_file_size_bytes` (10 MiB), `symlink_policy` ("ignore"), **`index_path` = ".nexusos/index.sqlite3"**,
  `search_max_results` (50), `search_snippet_length` (200), `server_host` (127.0.0.1),
  `server_port` (8765), `lint_max_file_size_bytes` (5 MiB), `lint_warn_empty_docs` (True).
  Methods: `merge_overrides`, `to_safe_dict`.
- `CheckStatus` (pass/warning/fail), `DoctorCheck`, `DoctorReport` (workspace_root, checks,
  passed, warnings, failures, healthy).

### 4.3 `src/nexusos/core/config.py`
- `load_toml(path)`, `load_config(config_path, apply_env=True)`, `load_config_effective(workspace_root)`,
  `config_to_safe_dict`.
- `_TOML_FIELD_MAP` maps `[section].key` → field. Supported sections: workspace, files, limits,
  search, server, lint, collections.
- **KNOWN GAP (Phase 2 must fix — t_23be9a75 §2):** unknown TOML sections/keys and unknown
  `NEXUSOS_*` env names are currently **silently ignored** (no validation). Phase 2 must reject
  unknown sections/keys with errors identifying section+key, and define a documented rule for
  unknown env names, without breaking the starter template's fields
  (including future-facing `[search]`, `[server]`, `[lint]`, `[collections]`).

### 4.4 `src/nexusos/core/path_safety.py`
`FORBIDDEN_PREFIXES`, `_parse_deny_list`, `is_denied_path`, `deny`, `is_root_or_home`,
`forbid_root_or_home`, `find_nearest_workspace_root`, `find_nested_workspaces`, `check_nesting`,
`check_symlink_escape`, `resolve_safe`, `workspace_root`, `validate_within_workspace`.
Phase 2 reuses these (must not bypass): validate DB path is workspace-bound, reject symlink escapes,
deny paths, nesting.

### 4.5 `src/nexusos/workspace/init.py`
`init_workspace(target, template, dry_run, adopt, env_deny)`, `build_workspace_identity`,
`load_workspace_identity(workspace_root)`, `_atomic_write`, templates (`STARTER_CONFIG`,
`BLANK_CONFIG`, `STARTER_README`, `BLANK_README`, `STARTER_SCHEMA`), `WSPACE_FILE =
".nexusos/workspace.json"`. Starter `nexusos.toml` includes `[collections]` mapping
inbox/raw/wiki/ops/mocs/journal — Phase 2 collection resolution reads these via config.

### 4.6 `src/nexusos/services/doctor.py`
`run_doctor(path, env_deny=None) -> DoctorReport`. Reuses path_safety + workspace identity.
Phase 2 `status`/`index` services follow this pattern (service returns typed model; CLI formats).

### 4.7 `src/nexusos/cli/main.py`
Pattern to follow for `index`/`status`: `@app.command()` functions calling a service,
`except NexusOSError as exc: typer.echo(f"Error: {exc}", err=True); raise typer.Exit(code=exc.exit_code)`,
`--json` via `model_dump(mode="json")`.

---

## 5. Intended integration point for Phase 2 (without changing public commands)

- Add `discovery/`, `parsing/`, `indexing/` packages + `services/index_service.py`,
  `services/status_service.py` per §3 of t_23be9a75. Do not modify `core/errors.py` semantics,
  `core/path_safety.py`, or `core/models.py` contracts except additive changes and the
  documented config-validation correction.
- Add **two new commands** `nexusos index` and `nexusos status` to `cli/main.py`.
  Existing commands (`version`, `init`, `doctor`, `config`) must keep exact current
  behavior/output/exit codes. Public contract change = additive only.
- **Config correction scope (t_23be9a75 §2):** tighten `config.py` validation (unknown
  section/key → ConfigError identifying the key; documented env-var rule). Keep every
  starter-template key valid. Add tests.
- DB location: `config.index_path` already defaults to `.nexusos/index.sqlite3`; must pass
  `validate_within_workspace` and never be created by `doctor`/`status`.
- Version bump: `pyproject.toml` → `0.1.0a2`, `src/nexusos/__init__.py` →
  `0.1.0-alpha.2`, plus CHANGELOG/ROADMAP/docs updates. No release tag without full verification.
- Verification gates (must all pass before completion): `uv sync`, `ruff check .`,
  `ruff format --check .`, `mypy src`, `pytest -q` (all 80 + new), `nexusos version`,
  plus the smoke sequence in t_23be9a75 §23 (init → doctor → status → index → status →
  incremental index after mutations, `--dry-run` creates no DB, status creates no DB,
  source immutability, symlink-escape rejection, lock conflict, rollback preservation,
  no absolute host paths, no search/MCP/mutation commands introduced).

## 6. Notes for downstream workers

- `examples/demo-vault/` exists but is **empty** — no fixture vault yet (Phase 2 §20 builds it).
- `tests/integration/` exists but is empty — Phase 2 adds integration tests there.
- The repository is **not a git repo** (`git status` fails at root; no `.git` found).
  If git-based work is required, initialize first or work in place as the workspace dir allows.
- Global PYTHONPATH on this machine points at the Hermes venv; always run project commands via
  `uv run` from the project root to avoid `pydantic_core`/wrong-version errors.
- `uv run pytest -q` collects exactly 80 tests today; keep that as the baseline floor.

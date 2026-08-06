# NexusOS v0.1 Release Roadmap

> **Current release:** `v0.1.0-alpha.3`  
> **Current phase:** release hardening complete; release candidate validation next  
> **Target:** a boring, trustworthy `v0.1.0` that installs cleanly, behaves consistently,
> and gives agents a stable local memory contract.

NexusOS has completed the planned **core feature scope** for v0.1. The work between
`alpha.2` and stable is not another feature sprint. It is a release-engineering pass:
close known hardening gaps, prove the package across supported platforms, freeze public
contracts, validate real MCP clients, and publish a reproducible release.

## Release policy

The following rules apply until `v0.1.0` ships:

1. **No new product scope.** Embeddings, ingestion connectors, guarded source writes,
   hosted services, OAuth, sync, and multi-user features remain post-v0.1 work.
2. **Every roadmap item needs evidence.** A task is complete only when its acceptance
   criteria and verification commands pass.
3. **Source immutability remains non-negotiable.** Read and retrieval operations must
   never mutate workspace source files.
4. **Documentation is part of the contract.** CLI help, configuration, MCP schemas,
   README examples, and release notes must agree with shipped behavior.
5. **Agents work one task at a time.** Do not combine unrelated roadmap items into a
   single change unless the task explicitly requires it.

## Release train

| Release | Purpose | Exit condition |
|---|---|---|
| `v0.1.0-alpha.2` | Core feature scope | Shipped |
| `v0.1.0-alpha.3` | Hardening and release infrastructure | Shipped |
| `v0.1.0-rc.1` | Real-world install and client validation | All RC tasks complete |
| `v0.1.0` | Stable release | All stable gates complete |

## Shipped foundation: `v0.1.0-alpha.2`

The current alpha includes:

- workspace initialization, identity, path boundaries, deny paths, and doctor checks
- deterministic Markdown and text indexing into SQLite with FTS5
- incremental indexing, stale-index detection, and transactional derived state
- search, browse, read, recent, links, and deterministic context retrieval
- workspace linting for broken links, ambiguous links, invalid frontmatter, orphans,
  duplicate slugs, stale indexes, oversized files, empty files, symlink escapes, and
  files outside configured collections
- MCP tools over stdio and Streamable HTTP
- a read-only local HTTP API and bundled inspection UI
- unit, integration, regression, and security coverage, with 414 tests reported for
  `alpha.2`

This is **core-scope complete**, not stable-release complete.

---

# `v0.1.0-alpha.3`: hardening and release infrastructure

## A3-01: Resolve accepted alpha findings

**Scope**

Close or explicitly defer each documented alpha finding:

- `F-03`: path-safety TOCTOU exposure
- `F-05`: relative deny paths resolving against the current working directory
- `F-06`: unbounded search configuration values
- `F-07`: unused `check_symlink_escape` defense
- `F-08`: operator-selected non-loopback serving policy

**Acceptance criteria**

- Every finding has a regression test or a written, reviewed deferral rationale.
- `README.md`, `SECURITY.md`, and release notes contain no stale limitation text.
- No finding disappears from documentation without an auditable resolution.

**Verify**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

## A3-02: Run the full suite across supported platforms

**Scope**

Upgrade CI from partial platform smoke coverage to the complete supported test contract.

**Acceptance criteria**

- Linux, macOS, and Windows run the full test suite on supported Python versions.
- Integration tests are no longer omitted from the platform matrix.
- CI failures identify the platform and Python version clearly.
- The README CI badge points to the actual workflow.

**Depends on:** A3-01

## A3-03: Define and enforce coverage policy

**Scope**

Replace the vague claim of “full test coverage” with a measurable policy.

**Acceptance criteria**

- A coverage threshold is documented and enforced in CI.
- Security-critical modules have targeted tests even when aggregate coverage passes.
- Coverage output is available as a CI artifact or job summary.
- Documentation uses precise language such as “full test suite” rather than claiming
  literal 100 percent coverage unless that is measured.

**Depends on:** A3-02

## A3-04: Validate build artifacts and clean installation

**Scope**

Prove the source distribution and wheel, not only the source checkout.

**Acceptance criteria**

- `python -m build` produces an sdist and wheel without warnings that affect users.
- Both artifacts install into clean environments.
- The installed package includes the bundled UI and required documentation files.
- `nexusos version`, `nexusos --help`, `nexusos demo`, and a minimal
  init/index/search flow pass from the installed wheel.
- Package metadata uses canonical repository URLs and the prerelease version is
  consistent across runtime and packaging metadata.

**Depends on:** A3-02

## A3-05: Freeze CLI, configuration, and exit-code contracts

> **Status:** Implemented for `v0.1.0-alpha.3` (kanban card `t_3a5ee653`).
> Deliverables: `docs/contracts.md` (full inventory), `tests/contracts/`
> (142 contract tests), CI step. Evidence in the card and
> `docs/release/v0.1-checklist.md`.

**Scope**

Audit the public interface that users and agents will depend on.

**Acceptance criteria**

- Every CLI command and public option is documented and covered by a smoke test.
- Configuration keys, environment variable names, defaults, validation behavior, and
  precedence are documented from the implementation.
- Exit codes are documented for user-facing commands with nontrivial failure modes.
- JSON output is stable, parseable, and tested for commands that advertise `--json`.
- Unsupported or internal behavior is not presented as a stable public contract.

**Depends on:** A3-01

## A3-06: Documentation and example verification

**Scope**

Treat documentation examples as executable release assets.

**Acceptance criteria**

- README quick start works from a clean checkout.
- MCP examples match current commands and transports.
- Configuration examples use valid keys and environment variable names.
- Contributor and agent instructions match the actual architecture and test layout.
- Internal links resolve and all referenced files exist.
- A documented release procedure exists.

**Depends on:** A3-04, A3-05

## A3-07: Security release review

**Scope**

Perform a focused review of filesystem boundaries, local servers, MCP transports,
configuration display, temporary files, and derived-state writes.

**Acceptance criteria**

- The threat model and supported deployment boundary are explicit.
- Source immutability tests cover CLI, HTTP, and MCP retrieval paths.
- Non-loopback behavior is intentional, tested, and documented without implying that
  the token is a complete internet-facing security layer.
- Vulnerability reporting instructions provide a private contact path before the
  repository is publicized as stable.
- No unresolved release-blocking security finding remains.

**Depends on:** A3-01, A3-05

## Alpha.3 release gate

`v0.1.0-alpha.3` may be tagged only when:

- A3-01 through A3-07 are complete
- the full CI matrix is green
- wheel and sdist installation tests pass
- roadmap, changelog, README, package version, and runtime version agree
- known limitations list only genuinely unresolved, accepted items

---

# `v0.1.0-rc.1`: real-world release candidate

## RC-01: Publish a prerelease package

- publish the release candidate to TestPyPI or PyPI as a prerelease
- verify installation using the public package index path
- confirm package metadata, included files, and console entry point

## RC-02: Clean-machine validation

Validate on clean Linux, macOS, and Windows environments:

```text
install -> version -> init -> doctor -> index -> status -> search -> lint -> MCP smoke
```

Record the exact environment and result for each supported platform.

## RC-03: MCP client compatibility

Validate representative clients against the documented stdio configuration and the
Streamable HTTP endpoint. At minimum, verify tool discovery, strict schemas, search,
read, context, status, and index behavior.

The release gate is based on protocol behavior, not a promise to support every client
or every client-specific configuration format.

## RC-04: Upgrade and schema validation

- open an `alpha.2` workspace with the release candidate
- verify supported schema migrations
- verify clear refusal of unsupported future schemas
- verify derived state can be deleted and rebuilt without source loss
- document downgrade expectations

## RC-05: Public contract freeze

After RC-05 begins, only release-blocking fixes may change:

- CLI command names and options
- configuration keys and defaults
- MCP tool names and schemas
- JSON response shapes
- documented exit-code behavior

## Release-candidate gate

`v0.1.0-rc.1` is complete when:

- RC-01 through RC-05 pass
- no release-blocking defect is open
- documentation matches the installed package
- clean-machine evidence is attached to the release or tracking issue

---

# `v0.1.0`: stable release

Stable requires all of the following:

- full supported CI matrix green
- reproducible wheel and sdist build
- clean installation verified on Linux, macOS, and Windows
- MCP protocol smoke tests passing
- upgrade and rebuild behavior verified
- security review complete
- no known release-blocking defect
- final changelog and release notes complete
- package published to PyPI
- signed or otherwise verified Git tag created
- README badges and installation instructions updated to stable

A release is not stable because the feature checklist is full. It is stable when the
published artifact, public contracts, documentation, and evidence all agree.

---

# Post-v0.1 direction

These are product directions, not commitments for the v0.1 release train:

- ingestion pipelines for web pages, PDFs, and external services
- guarded write proposals with diffs and approvals
- embeddings and optional vector retrieval
- NexusOS Studio operational interface
- fleet memory for multi-agent coordination
- encrypted sync and team collaboration
- hosted MCP with authentication and OAuth

They should move into versioned proposals only after `v0.1.0` is released.
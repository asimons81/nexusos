# Releasing NexusOS

This document defines the evidence required to cut a NexusOS prerelease or stable
release. It complements the version gates in [../ROADMAP.md](../ROADMAP.md).

A release is an artifact and contract, not merely a commit with a version change.

## Roles

The release owner is responsible for:

- confirming the roadmap gate is complete
- freezing the intended commit
- verifying version and documentation consistency
- building and testing distribution artifacts
- recording platform and MCP validation evidence
- publishing the package and Git tag
- writing release notes and rollback guidance

A coding agent may prepare and verify release work, but publication credentials and final
release authority remain with the maintainer.

## Version scheme

NexusOS uses PEP 440 package versions and human-readable runtime versions.

Examples:

| Release | `pyproject.toml` | Runtime and docs |
|---|---|---|
| Alpha 3 | `0.1.0a3` | `0.1.0-alpha.3` |
| RC 1 | `0.1.0rc1` | `0.1.0-rc.1` |
| Stable | `0.1.0` | `0.1.0` |

The version must agree across:

- `pyproject.toml`
- `src/nexusos/__init__.py`
- README badge and status text
- `CHANGELOG.md`
- `ROADMAP.md`
- release tag and release title

The package version may use PEP 440 syntax while the runtime string uses the more
readable hyphenated form.

## 1. Confirm the release gate

Before changing the version, verify the target gate in
[../ROADMAP.md](../ROADMAP.md).

For a stable release, confirm at minimum:

- all alpha and release-candidate tasks are complete
- no release-blocking issue remains open
- full supported CI matrix is green
- package artifacts passed clean-install tests
- MCP protocol validation is recorded
- security review is complete
- documentation matches the installed package

Do not convert an incomplete gate into a release by editing the checklist.

## 2. Prepare the release branch

Create a focused release branch from the intended base commit. Avoid unrelated refactors
or feature work after the release freeze begins.

Update:

- package and runtime versions
- changelog entry and release date
- roadmap current-release status
- README badge, installation text, and known limitations
- security supported-version table

For an RC or stable release, public CLI, configuration, MCP, JSON, and exit-code
contracts should already be frozen.

## 3. Run the repository gate

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run nexusos version
```

Record the exact commit, operating system, Python version, and command results.

The local gate does not replace the supported CI matrix.

## 4. Build artifacts

Start from a clean tree:

```bash
git status --short
rm -rf dist build
uv run --with build python -m build
uv run --with twine twine check dist/*
```

Expected output:

- one source distribution
- one wheel
- no metadata or README rendering errors

Inspect the archive contents. Confirm the wheel includes the package, bundled UI, and all
runtime-required resources. Confirm the source distribution includes the maintained
project documents declared in packaging configuration.

## 5. Test the wheel in a clean environment

Do not test only the source checkout.

Create a new environment outside the repository, install the built wheel, and run:

```text
nexusos version
nexusos --help
nexusos demo
nexusos init <temp-workspace>
nexusos doctor --workspace <temp-workspace>
nexusos index --workspace <temp-workspace>
nexusos status --workspace <temp-workspace>
nexusos search <term> --workspace <temp-workspace>
nexusos lint --workspace <temp-workspace>
```

Also verify that the bundled inspection UI can be loaded from the installed artifact.

Repeat the clean-install smoke on supported Linux, macOS, and Windows environments before
stable release.

## 6. Validate MCP

From the installed artifact, validate both transports required by the target gate.

stdio:

```bash
nexusos mcp --workspace /path/to/workspace
```

Streamable HTTP:

```bash
nexusos serve --transport streamable-http --workspace /path/to/workspace
```

Record evidence for:

- initialization and shutdown
- tool discovery
- strict schema rejection of extra arguments
- `status`, `search`, `read`, `context`, and `index`
- missing and stale index behavior
- typed tool errors
- source immutability after retrieval calls

Representative client validation is required for the release candidate, but the
protocol contract remains the source of truth.

## 7. Validate upgrades and rebuilds

For RC and stable releases:

1. create or preserve a workspace from the previous published prerelease
2. open and index it with the candidate artifact
3. verify supported schema migration behavior
4. verify clear refusal of unsupported future schemas
5. delete derived index state
6. rebuild it from source files
7. compare source bytes before and after

Document downgrade expectations. NexusOS must never imply that a schema downgrade is
safe when it has not been implemented and tested.

## 8. Prepare release notes

Release notes should include:

- release status: alpha, RC, or stable
- user-visible additions and fixes
- security-relevant changes
- migration or compatibility notes
- known limitations
- verification summary
- link to the complete changelog

Avoid claims such as “fully secure,” “all platforms supported,” or “full coverage” unless
the release evidence precisely supports them.

## 9. Publish

For a prerelease, use the configured package index and ensure the version is recognized as
a prerelease.

A typical publication path is:

```bash
uv publish dist/*
```

Credentials must be supplied through the maintainer's secure environment. Never commit
API tokens, publish them in logs, or place them in repository configuration.

After publishing:

1. install the package from the public index into a clean environment
2. rerun version and minimal workflow smoke tests
3. create the Git tag from the exact verified commit
4. create the GitHub release with the prepared notes
5. verify README installation instructions

## 10. Tagging

Use a tag that matches the human-readable release version:

```text
v0.1.0-alpha.3
v0.1.0-rc.1
v0.1.0
```

The tag must point to the exact commit whose artifacts were built and tested.

## Release evidence template

```markdown
## Release

Version: v0.1.0-...
Commit: <sha>

## Roadmap gate

- [ ] Required task IDs complete
- [ ] No release blocker open

## Repository verification

- [ ] Ruff check
- [ ] Ruff format check
- [ ] mypy strict
- [ ] Full pytest suite
- [ ] Supported CI matrix

## Artifacts

- [ ] sdist built and inspected
- [ ] wheel built and inspected
- [ ] metadata check passed
- [ ] clean wheel install passed

## Platforms

- [ ] Linux
- [ ] macOS
- [ ] Windows

## MCP

- [ ] stdio protocol smoke
- [ ] Streamable HTTP smoke
- [ ] representative client validation where required
- [ ] source immutability proof

## Contracts

- [ ] versions agree
- [ ] README and docs agree
- [ ] changelog and release notes complete
- [ ] known limitations current
- [ ] security review complete
```

## Failed release or rollback

If publication succeeds but validation fails:

- do not reuse the published version number
- document the defect immediately
- prepare a new patch or prerelease version
- mark the bad release clearly in release notes
- avoid deleting evidence needed to diagnose the failure

Package indexes may not permit replacing an existing artifact. Treat every publication as
permanent and verify before uploading.
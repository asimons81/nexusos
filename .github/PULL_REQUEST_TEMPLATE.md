## Scope

Roadmap task or defect:

<!-- Example: A3-04 or F-06 -->

## Contract

<!--
Describe the user, agent, CLI, configuration, JSON, MCP, packaging, migration, or security
contract changed by this pull request. Write `No public contract change` when appropriate.
-->

## Changes

<!-- Summarize the smallest coherent set of changes. -->

## Acceptance criteria

<!-- Copy the applicable roadmap criteria and mark only evidence-backed items complete. -->

- [ ] Required behavior is implemented
- [ ] Regression or contract tests are included
- [ ] Documentation matches implementation
- [ ] Deferred work is explicit

## Verification

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest -q`
- [ ] `uv run nexusos version`
- [ ] Roadmap-specific verification completed

Paste concise results or link CI evidence:

```text
<verification evidence>
```

## Security and data safety

- [ ] Source immutability is preserved
- [ ] No personal files, paths, credentials, or private workspace data were added
- [ ] Network exposure changes are documented and tested
- [ ] Security-relevant behavior is reflected in `SECURITY.md`

## Documentation

- [ ] README updated when user-facing behavior changed
- [ ] Relevant `docs/` pages updated
- [ ] `CHANGELOG.md` updated for user-visible behavior
- [ ] Roadmap status remains accurate

## Limitations

<!-- List accepted limitations or write `None`. -->
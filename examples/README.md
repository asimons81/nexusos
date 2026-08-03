# NexusOS examples

This directory holds runnable NexusOS examples. It is included in the sdist
(`examples/` is declared in `pyproject.toml`).

## Quick start

The fastest example is the built-in demo, which creates a synthetic workspace,
walks through `init → index → status → doctor`, and prints usage examples:

```bash
uv run nexusos demo                # from a source checkout
nexusos demo --path /tmp/demo-vault --remove
```

`--path` places the demo vault at a specific location; `--remove` deletes it
when the walkthrough finishes.

## Create your own example workspace

```bash
nexusos init --template starter ./example-workspace
nexusos doctor --workspace ./example-workspace
nexusos index --workspace ./example-workspace
nexusos search "hello" --workspace ./example-workspace
```

The `starter` template creates a 22-entry vault with the standard folder
convention (`inbox/`, `raw/`, `wiki/`, `ops/`, `mocs/`, `journal/`) plus
`nexusos.toml`, `README.md`, and `SCHEMA.md`. See
[../docs/install.md](../docs/install.md) for full instructions.

> Note: the starter template's `SCHEMA.md` documents `[[page-name]]` wiki-link
> syntax as an example. `nexusos lint` flags it as an unresolved link — that is
> expected template behavior, not a defect.

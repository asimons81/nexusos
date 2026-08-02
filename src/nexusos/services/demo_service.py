"""Scripted walkthrough of NexusOS core features (`nexusos demo`).

Developer tooling: creates a fresh synthetic demo vault, seeds it with sample
Markdown documents (frontmatter + wiki links), runs the real init → index →
status → doctor pipeline, and prints the walkthrough with the equivalent CLI
commands. All documents are synthetic; the vault lives in a temporary
directory by default and never touches personal paths.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import cast

from nexusos.core.errors import NexusOSError
from nexusos.services.doctor import run_doctor
from nexusos.services.index_service import index_workspace
from nexusos.services.status_service import get_status
from nexusos.workspace.init import init_workspace

#: Synthetic sample documents: relative path → content.
#: These are fictional, generic examples — no personal or private data.
DEMO_DOCUMENTS: dict[str, str] = {
    "wiki/concepts/agents.md": """---
title: AI Agents
type: concept
status: active
tags: [agents, memory]
---
# AI Agents

Agents are programs that act toward goals. They rely on [[memory]] to
persist knowledge between runs, and they cite their sources with links.
""",
    "wiki/concepts/memory.md": """---
title: Memory
type: concept
status: active
tags: [memory]
---
# Memory

Memory is the durable layer that [[agents]] consult. NexusOS indexes
Markdown documents so agents can search and browse them deterministically.
""",
    "wiki/entities/atlas.md": """---
title: Atlas
type: entity
status: active
---
# Atlas

Atlas is a fictional assistant that keeps notes in a NexusOS vault. It
maintains a map of concepts such as [[memory]].
""",
    "raw/notes/field-notes.md": """# Field Notes

Observations recorded during a demo:

- Wiki links resolve deterministically: [[agents]]
- Broken links are tracked for later linting: [[does-not-exist]]
""",
    "journal/demo-entry.md": """---
title: Demo Journal Entry
type: journal
---
# Demo Journal Entry

Today we walked through the NexusOS core pipeline: init, index, status,
and doctor. See [[memory]] for the underlying concept.
""",
}

#: Step names printed by the CLI (command → description).
DEMO_STEPS: list[tuple[str, str]] = [
    ("init", "initialize a fresh starter workspace"),
    ("seed", "write synthetic sample documents with frontmatter and wiki links"),
    ("index", "index the workspace (discover, parse, chunk, resolve links)"),
    ("status", "report index status and staleness"),
    ("doctor", "run the health checks"),
]


def run_demo(target: Path | None = None, *, remove: bool = False) -> dict[str, object]:
    """Run the scripted demo walkthrough.

    Args:
        target: Where to create the demo vault. Defaults to a fresh
            temporary directory (kept for inspection unless ``remove``).
        remove: Remove the demo vault after the walkthrough completes.

    Returns a JSON-serializable summary: path, steps, status, doctor state.

    Raises:
        NexusOSError: When ``target`` exists and is non-empty (the demo never
            overwrites user content).
    """
    if target is None:
        target = Path(tempfile.mkdtemp(prefix="nexusos-demo-"))
    target = Path(target).expanduser()

    if target.exists() and target.is_dir() and any(target.iterdir()):
        raise NexusOSError(
            f"demo path {target} is not empty; choose an empty or non-existent path",
            exit_code=2,
        )

    steps: list[dict[str, str]] = []
    created = target.exists() and target.is_dir()

    # Step 1 — init
    plan = init_workspace(target, template="starter", adopt=created)
    steps.append(
        {
            "command": f"nexusos init {target}",
            "detail": f"created {len(plan)} entries (starter template)",
        }
    )

    # Step 2 — seed sample documents
    written = 0
    for rel_path, content in DEMO_DOCUMENTS.items():
        doc = target / rel_path
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(content, encoding="utf-8")
        written += 1
    steps.append(
        {
            "command": f"nexusos index --workspace {target}",
            "detail": f"seeded {written} synthetic sample documents",
        }
    )

    # Step 3 — index
    run = index_workspace(target)
    steps.append(
        {
            "command": f"nexusos index --workspace {target}",
            "detail": (
                f"files seen={run.files_seen}, added={run.files_added}, "
                f"unchanged={run.files_unchanged}, failed={run.documents_failed}"
            ),
        }
    )

    # Step 4 — status
    status = get_status(target)
    steps.append(
        {
            "command": f"nexusos status --workspace {target}",
            "detail": (
                f"status={status.get('status')}, documents={status.get('document_count', 0)}, "
                f"chunks={status.get('chunk_count', 0)}"
            ),
        }
    )

    # Step 5 — doctor
    report = run_doctor(target)
    steps.append(
        {
            "command": f"nexusos doctor --workspace {target}",
            "detail": (
                f"passed={report.passed}, warnings={report.warnings}, "
                f"failures={report.failures}, healthy={report.healthy}"
            ),
        }
    )

    result: dict[str, object] = {
        "path": str(target),
        "steps": steps,
        "status": status,
        "doctor_healthy": report.healthy,
    }

    if remove:
        shutil.rmtree(target, ignore_errors=True)

    return result


def print_demo(result: dict[str, object]) -> None:
    """Print the demo walkthrough with visible usage examples."""
    import sys

    path = str(result["path"])
    sys.stdout.write("NexusOS Demo — scripted walkthrough of core features\n")
    sys.stdout.write("=" * 62 + "\n")
    sys.stdout.write(f"Demo vault: {path}\n\n")

    steps = cast("list[dict[str, str]]", result["steps"])
    for i, step in enumerate(steps, start=1):
        if isinstance(step, dict):
            sys.stdout.write(f"Step {i}: {step.get('command', '')}\n")
            sys.stdout.write(f"  -> {step.get('detail', '')}\n")

    status = result.get("status")
    if isinstance(status, dict):
        final_line = (
            f"\nFinal status: {status.get('status')} "
            f"(documents={status.get('document_count', 0)}, "
            f"chunks={status.get('chunk_count', 0)})\n"
        )
        sys.stdout.write(final_line)
    sys.stdout.write(f"Doctor healthy: {'yes' if result.get('doctor_healthy') else 'NO'}\n")

    sys.stdout.write("\nUsage examples\n" + "-" * 62 + "\n")
    sys.stdout.write("  nexusos init ~/my-vault\n")
    sys.stdout.write("  nexusos doctor --workspace ~/my-vault\n")
    sys.stdout.write("  nexusos index --workspace ~/my-vault\n")
    sys.stdout.write("  nexusos status --workspace ~/my-vault\n")
    sys.stdout.write("  nexusos config show --workspace ~/my-vault --effective\n")
    sys.stdout.write("  nexusos serve --workspace ~/my-vault --port 8765\n")

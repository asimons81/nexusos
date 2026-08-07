"""Documentation contract checks.

Public Markdown is part of the release surface. Relative links must resolve in
the checkout so they also work in GitHub and the source distribution.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)#]+)(?:#[^)]+)?\)")


def test_public_markdown_relative_links_resolve() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    documents = [
        repo_root / name
        for name in (
            "README.md",
            "ROADMAP.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "AGENTS.md",
        )
    ]
    documents.extend((repo_root / "docs").rglob("*.md"))
    documents.extend((repo_root / "examples").rglob("*.md"))

    broken: list[str] = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for match in _MARKDOWN_LINK.finditer(text):
            target = match.group(1)
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (document.parent / target).resolve().exists():
                line = text.count("\n", 0, match.start()) + 1
                broken.append(f"{document.relative_to(repo_root)}:{line}: {target}")

    assert broken == [], "broken relative Markdown links:\n" + "\n".join(broken)


def test_sdist_excludes_self_referential_artifact_manifest() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    sdist = config["tool"]["hatch"]["build"]["targets"]["sdist"]

    assert "docs/release/v0.1.0-manifest.md" in sdist["exclude"]

"""Canonical wiki-link target suffix precedence.

Single source of truth for the order in which document filename suffixes
are stripped and re-appended when resolving wiki-link targets. ``.md``
first is the canonical order: when both ``foo.md`` and ``foo.markdown``
exist, a link to ``[[foo]]`` and the navigation lookup for ``foo`` both
resolve to ``foo.md``.

Used by the index-time graph resolver, the navigation kernel, the parsing
slug normalizers, and the vault linter so every surface agrees on the same
resolution rule (audit HIGH-2).
"""

from __future__ import annotations

#: Canonical suffix precedence for wiki-link resolution (``.md`` first).
LINK_SUFFIXES: tuple[str, ...] = (".md", ".markdown", ".txt")

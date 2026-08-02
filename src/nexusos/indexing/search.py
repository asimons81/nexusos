"""Search query construction for the NexusOS indexing kernel.

Search is SQLite FTS5 only (see ``docs/architecture.md`` — Deterministic
Search). User input is never interpolated into a raw MATCH expression:
:func:`build_fts_query` wraps every whitespace-separated word in a quoted
prefix phrase so that FTS5 operators (``AND``, ``OR``, ``NOT``, ``NEAR``,
parentheses, colons, quotes) are treated as literal text and cannot change
the query's meaning or raise a syntax error.
"""

from __future__ import annotations

import re

#: FTS5 phrases are built as ``"word"*`` — quoted for safety, with the
#: prefix star OUTSIDE the closing quote so ``kern`` finds ``kernel``.
#: (A star inside the quotes is treated as a token separator by unicode61.)
_TOKEN_SPLIT_RE = re.compile(r"\s+")


def build_fts_query(term: str) -> str:
    """Translate a user search term into a safe FTS5 MATCH expression.

    Each whitespace-separated word becomes a quoted prefix phrase joined by
    an implicit AND: ``"kernel"* "search"*``. Embedded double quotes are
    escaped by doubling (the FTS5 phrase escape). A trailing ``*`` on a
    word is collapsed so users cannot craft ``**`` sequences.

    Raises:
        ValueError: if ``term`` is empty or whitespace only.
    """
    stripped = term.strip()
    if not stripped:
        raise ValueError("search term must not be empty")

    phrases: list[str] = []
    for word in stripped.split():
        if not word:
            continue
        # Collapse a user-supplied trailing star; the builder appends one.
        word = word.rstrip("*")
        escaped = word.replace('"', '""')
        phrases.append(f'"{escaped}"*')
    return " ".join(phrases)

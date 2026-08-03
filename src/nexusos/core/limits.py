"""Shared bound limits for search, browse, recent, context, and MCP surfaces.

Finding F-06: search/browse/MCP accepted negative or unbounded limits, so
``--limit -1`` returned every row (SQLite ``LIMIT -1`` is unlimited) and the
CLI/MCP semantics were inconsistent. Every surface that takes a row limit now
validates it against these shared bounds in the service layer (used by CLI,
config, JSON, and MCP), so behavior is consistent everywhere.
"""

from __future__ import annotations

#: Smallest row limit accepted by any list-style command.
MIN_LIMIT = 1
#: Largest row limit accepted by ``search``.
MAX_SEARCH_LIMIT = 500
#: Largest row limit accepted by ``browse``.
MAX_BROWSE_LIMIT = 1000
#: Largest row limit accepted by ``recent``.
MAX_RECENT_LIMIT = 100
#: Largest sibling limit accepted by ``context``.
MAX_CONTEXT_SIBLING_LIMIT = 100
#: Largest snippet token budget accepted by ``search``.
MAX_SNIPPET_TOKENS = 10_000


def validate_limit(value: int, *, name: str, maximum: int) -> int:
    """Return ``value`` when it is in ``[MIN_LIMIT, maximum]``.

    Raises:
        ValueError: when the value is outside the accepted range.
    """
    if value < MIN_LIMIT or value > maximum:
        raise ValueError(f"{name} must be between {MIN_LIMIT} and {maximum}, got {value}")
    return value

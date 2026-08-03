"""Service layer for workspace full-text search."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from nexusos.core.errors import IndexingError, WorkspaceNotFoundError
from nexusos.core.limits import (
    MAX_SEARCH_LIMIT,
    MAX_SEARCH_TERM_LENGTH,
    MAX_SNIPPET_TOKENS,
    validate_limit,
)
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import SearchHit
from nexusos.workspace.init import load_workspace_identity


class SearchReport:
    """A search report: the query, total hit count, and ranked hits.

    JSON-serializable for the CLI ``--json`` path.
    """

    def __init__(self, *, query: str, results: list[SearchHit]) -> None:
        self.query = query
        self.total = len(results)
        self.results = results

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "total": self.total,
            "results": [hit.model_dump(mode="json") for hit in self.results],
        }


def search_workspace(
    workspace_root: Path,
    term: str,
    *,
    limit: int = 50,
    snippet_tokens: int = 200,
) -> SearchReport:
    """Run a full-text search against a workspace's index.

    Read-only: never creates the index database. Raises
    :class:`WorkspaceNotFoundError` when the directory is not a NexusOS
    workspace and :class:`IndexingError` when no index exists yet.

    Args:
        workspace_root: Resolved workspace root path.
        term: Plain-text user query.
        limit: Maximum number of hits to return (must be in [1, 500]).
        snippet_tokens: Max tokens for each FTS5 snippet excerpt (must be
            positive and bounded).

    Raises:
        IndexingError: when ``limit`` or ``snippet_tokens`` is out of range
            (F-06), ``term`` exceeds ``MAX_SEARCH_TERM_LENGTH`` (F-13), the
            workspace is uninitialized, or the index is missing.
    """
    try:
        limit = validate_limit(limit, name="limit", maximum=MAX_SEARCH_LIMIT)
        snippet_tokens = validate_limit(
            snippet_tokens, name="snippet_tokens", maximum=MAX_SNIPPET_TOKENS
        )
    except ValueError as exc:
        raise IndexingError(str(exc), exit_code=2) from exc

    if len(term) > MAX_SEARCH_TERM_LENGTH:
        raise IndexingError(
            f"search term must be at most {MAX_SEARCH_TERM_LENGTH} characters; got {len(term)}",
            exit_code=2,
        )

    identity = load_workspace_identity(workspace_root)
    if identity is None:
        raise WorkspaceNotFoundError(
            f"no NexusOS workspace at {workspace_root}; run `nexusos init` first",
            exit_code=2,
        )

    kernel = IndexKernel(workspace_root)
    # Read-only invariant: an initialized workspace with no index database
    # must raise instead of creating one (mirrors status_service).
    if not kernel.index_exists():
        raise IndexingError(
            "no index database; run `nexusos index` first",
            exit_code=2,
        )
    try:
        # create_parent=False keeps search read-only; mode=ro URI means a
        # read-only .nexusos directory does not break search (WAL is skipped).
        kernel.open(create_parent=False, read_only=True)
    except Exception as exc:
        if isinstance(exc, IndexingError):
            raise
        raise IndexingError(f"cannot open index database: {exc}", exit_code=3)

    try:
        hits = kernel.search(term, limit=limit, snippet_tokens=snippet_tokens)
    finally:
        kernel.close()

    return SearchReport(query=term, results=hits)

"""Wiki-link graph resolution after all documents are indexed.

Constructs the link graph from all known wiki-link targets, resolves each
target to its document ID (or marks it unresolved/ambiguous), and returns
the resolved links.
"""

from __future__ import annotations

from nexusos.core.link_suffixes import LINK_SUFFIXES
from nexusos.indexing.kernel import IndexKernel
from nexusos.indexing.models import IndexedLink


def resolve_links(
    kernel: IndexKernel,
    links: list[tuple[str, list[IndexedLink]]],
    *,
    all_document_ids: set[str],
) -> list[tuple[str, list[IndexedLink]]]:
    """Resolve wiki-link targets against all known documents.

    Each element of ``links`` is a (document_id, [links_from_that_document]).
    Returns the same structure with ``target_document_id``, ``resolved``, and
    ``resolution_state`` populated on each link.

    Resolution rules (per Phase 2 contract):
    1. Strip .md/.markdown suffix from target.
    2. Resolve explicit relative paths first.
    3. Resolve unique filename stems next.
    4. Do not choose arbitrarily when multiple documents match (ambiguous).
    5. Heading fragments do not affect document resolution.
    """
    # Build lookup maps: normalized_path → document_id, stem → [document_ids]
    all_candidates = kernel._db.list_documents()
    path_to_id: dict[str, str] = {}
    stem_to_ids: dict[str, list[str]] = {}

    for c in all_candidates:
        path_to_id[c.normalized_path] = c.document_id
        stem = _path_stem(c.normalized_path)
        stem_to_ids.setdefault(stem, []).append(c.document_id)

    resolved_list: list[tuple[str, list[IndexedLink]]] = []

    for doc_id, doc_links in links:
        resolved_links: list[IndexedLink] = []
        for link in doc_links:
            slug = link.target_slug

            # Tier 1: exact normalized-path match
            target_id = path_to_id.get(slug)
            if target_id is not None and target_id in all_document_ids:
                resolved_links.append(
                    link.model_copy(
                        update={
                            "target_document_id": target_id,
                            "resolved": True,
                            "resolution_state": "resolved",
                        }
                    )
                )
                continue

            # Try with suffix
            found = False
            for suffix in LINK_SUFFIXES:
                target_id = path_to_id.get(slug + suffix)
                if target_id is not None and target_id in all_document_ids:
                    resolved_links.append(
                        link.model_copy(
                            update={
                                "target_document_id": target_id,
                                "resolved": True,
                                "resolution_state": "resolved",
                            }
                        )
                    )
                    found = True
                    break
            if found:
                continue

            # Tier 2: filename stem match
            stem = slug.rsplit("/", 1)[-1]
            matching = stem_to_ids.get(stem, [])
            matching = [mid for mid in matching if mid in all_document_ids]

            if len(matching) == 0:
                resolved_links.append(
                    link.model_copy(
                        update={
                            "target_document_id": None,
                            "resolved": False,
                            "resolution_state": "unresolved",
                        }
                    )
                )
            elif len(matching) == 1:
                resolved_links.append(
                    link.model_copy(
                        update={
                            "target_document_id": matching[0],
                            "resolved": True,
                            "resolution_state": "resolved",
                        }
                    )
                )
            else:
                resolved_links.append(
                    link.model_copy(
                        update={
                            "target_document_id": None,
                            "resolved": False,
                            "resolution_state": "ambiguous",
                        }
                    )
                )

        resolved_list.append((doc_id, resolved_links))

    return resolved_list


def _path_stem(normalized_path: str) -> str:
    """Return the filename stem (no directory, no suffix)."""
    name = normalized_path.rsplit("/", 1)[-1]
    for suffix in LINK_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name

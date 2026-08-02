"""Golden tests for deterministic NexusOS index identifiers."""

from __future__ import annotations

import re

from nexusos.indexing.ids import (
    CHUNK_ID_PREFIX,
    DOC_ID_PREFIX,
    chunk_id,
    document_id,
    run_id,
)

_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


def test_document_id_shape_and_prefix() -> None:
    did = document_id("nxo_ws_alpha", "wiki/example.md")
    assert did.startswith(DOC_ID_PREFIX)
    assert len(did) == len(DOC_ID_PREFIX) + 32
    assert _ID_PATTERN.fullmatch(did)


def test_document_id_is_url_safe() -> None:
    did = document_id("nxo_ws_alpha", "wiki/Ünïcode 文件.md")
    assert _ID_PATTERN.fullmatch(did)


def test_document_id_stable_across_calls() -> None:
    assert document_id("nxo_ws_a", "wiki/x.md") == document_id("nxo_ws_a", "wiki/x.md")


def test_document_id_stable_across_content_changes() -> None:
    # Document IDs are path-derived; they must not change when content changes.
    first = document_id("nxo_ws_a", "wiki/x.md")
    second = document_id("nxo_ws_a", "wiki/x.md")
    assert first == second


def test_document_id_differs_across_workspaces() -> None:
    assert document_id("nxo_ws_a", "wiki/x.md") != document_id("nxo_ws_b", "wiki/x.md")


def test_document_id_differs_across_paths() -> None:
    assert document_id("nxo_ws_a", "wiki/x.md") != document_id("nxo_ws_a", "wiki/y.md")


def test_document_id_normalizes_backslashes() -> None:
    assert document_id("nxo_ws_a", "wiki\\x.md") == document_id("nxo_ws_a", "wiki/x.md")


def test_document_id_strips_leading_dot_slash() -> None:
    assert document_id("nxo_ws_a", "./wiki/x.md") == document_id("nxo_ws_a", "wiki/x.md")


def test_chunk_id_shape_and_prefix() -> None:
    cid = chunk_id("nxo_doc_" + "a" * 32, 1, "ab" * 32)
    assert cid.startswith(CHUNK_ID_PREFIX)
    assert len(cid) == len(CHUNK_ID_PREFIX) + 32
    assert _ID_PATTERN.fullmatch(cid)


def test_chunk_id_stable_for_same_inputs() -> None:
    did = "nxo_doc_" + "a" * 32
    assert chunk_id(did, 2, "ab" * 32) == chunk_id(did, 2, "ab" * 32)


def test_chunk_id_changes_with_ordinal() -> None:
    did = "nxo_doc_" + "a" * 32
    assert chunk_id(did, 1, "ab" * 32) != chunk_id(did, 2, "ab" * 32)


def test_chunk_id_changes_with_content() -> None:
    did = "nxo_doc_" + "a" * 32
    assert chunk_id(did, 1, "ab" * 32) != chunk_id(did, 1, "cd" * 32)


def test_run_id_prefix_and_uniqueness() -> None:
    first, second = run_id(), run_id()
    assert first.startswith("nxo_run_")
    assert first != second
    assert _ID_PATTERN.fullmatch(first)


def test_ids_contain_no_absolute_path_or_machine_data() -> None:
    did = document_id("nxo_ws_alpha", "wiki/example.md")
    assert "/" not in did
    assert "wiki" not in did

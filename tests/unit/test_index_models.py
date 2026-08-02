"""Unit tests for indexing kernel models."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from nexusos.indexing.ids import chunk_id, document_id
from nexusos.indexing.models import (
    IndexCounts,
    IndexedChunk,
    IndexedDocument,
    IndexedHeading,
    IndexedLink,
    IndexRunRecord,
)

_WS = "nxo_ws_modeltest"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _doc(**overrides: object) -> IndexedDocument:
    path = "wiki/alpha.md"
    doc_id = document_id(_WS, path)
    body = "alpha body"
    values: dict[str, object] = {
        "document_id": doc_id,
        "relative_path": path,
        "normalized_path": path,
        "collection": "wiki",
        "title": "Alpha",
        "file_type": "markdown",
        "authority_class": "unknown",
        "mtime_ns": 1_700_000_000_000_000_000,
        "size_bytes": 42,
        "content_sha256": _sha("content"),
        "frontmatter_json": "{}",
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "line_count": 3,
        "chunks": [
            IndexedChunk(
                chunk_id=chunk_id(doc_id, 1, _sha(body)),
                document_id=doc_id,
                ordinal=1,
                heading_path=("Alpha",),
                start_line=1,
                end_line=2,
                text=body,
                content_sha256=_sha(body),
            )
        ],
    }
    values.update(overrides)
    return IndexedDocument(**values)


def test_document_id_must_match_pattern() -> None:
    with pytest.raises(ValidationError):
        _doc(document_id="bad_id")


def test_relative_path_rejects_absolute() -> None:
    with pytest.raises(ValidationError):
        _doc(relative_path="/etc/passwd", normalized_path="/etc/passwd")


def test_relative_path_rejects_windows_drive() -> None:
    with pytest.raises(ValidationError):
        _doc(relative_path="C:\\Users\\x.md", normalized_path="C:\\Users\\x.md")


def test_relative_path_rejects_dot_dot() -> None:
    with pytest.raises(ValidationError):
        _doc(relative_path="../escape.md", normalized_path="../escape.md")


def test_relative_path_rejects_backslashes() -> None:
    with pytest.raises(ValidationError):
        _doc(relative_path="wiki\\alpha.md", normalized_path="wiki\\alpha.md")


def test_content_sha256_must_be_hex() -> None:
    with pytest.raises(ValidationError):
        _doc(content_sha256="not-a-hash")


def test_chunk_ordinals_must_be_contiguous() -> None:
    doc_id = document_id(_WS, "wiki/alpha.md")
    with pytest.raises(ValidationError):
        _doc(
            chunks=[
                IndexedChunk(
                    chunk_id=chunk_id(doc_id, 1, _sha("a")),
                    document_id=doc_id,
                    ordinal=1,
                    start_line=1,
                    end_line=1,
                    text="a",
                    content_sha256=_sha("a"),
                ),
                IndexedChunk(
                    chunk_id=chunk_id(doc_id, 3, _sha("c")),
                    document_id=doc_id,
                    ordinal=3,
                    start_line=1,
                    end_line=1,
                    text="c",
                    content_sha256=_sha("c"),
                ),
            ]
        )


def test_chunk_end_line_must_follow_start_line() -> None:
    doc_id = document_id(_WS, "wiki/alpha.md")
    with pytest.raises(ValidationError):
        _doc(
            chunks=[
                IndexedChunk(
                    chunk_id=chunk_id(doc_id, 1, _sha("a")),
                    document_id=doc_id,
                    ordinal=1,
                    start_line=5,
                    end_line=2,
                    text="a",
                    content_sha256=_sha("a"),
                )
            ]
        )


def test_chunk_document_id_must_match_owner() -> None:
    with pytest.raises(ValidationError):
        _doc(
            chunks=[
                IndexedChunk(
                    chunk_id=chunk_id("nxo_doc_" + "b" * 32, 1, _sha("a")),
                    document_id="nxo_doc_" + "b" * 32,
                    ordinal=1,
                    start_line=1,
                    end_line=1,
                    text="a",
                    content_sha256=_sha("a"),
                )
            ]
        )


def test_link_resolution_state_restricted() -> None:
    with pytest.raises(ValidationError):
        IndexedLink(source_line=1, raw_target="x", target_slug="x", resolution_state="maybe")


def test_link_defaults_unresolved() -> None:
    link = IndexedLink(source_line=1, raw_target="x", target_slug="x")
    assert link.resolved is False
    assert link.resolution_state == "unresolved"
    assert link.target_document_id is None


def test_empty_document_without_chunks_is_valid() -> None:
    doc = _doc(chunks=[])
    assert doc.chunks == []


def test_run_record_defaults() -> None:
    run = IndexRunRecord(run_id="nxo_run_x", started_at="now", mode="incremental")
    assert run.success is False
    assert run.files_seen == 0
    assert run.completed_at is None


def test_counts_model() -> None:
    counts = IndexCounts(
        document_count=1,
        chunk_count=2,
        heading_count=3,
        resolved_link_count=1,
        unresolved_link_count=0,
        ambiguous_link_count=0,
    )
    assert counts.document_count == 1


def test_document_json_serializable() -> None:
    import json

    json.dumps(_doc().model_dump(mode="json"))


def test_heading_validation() -> None:
    with pytest.raises(ValidationError):
        IndexedHeading(ordinal=0, level=1, text="x", normalized_text="x", line=1)

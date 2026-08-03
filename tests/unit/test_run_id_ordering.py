"""Regression tests for index-run ordering."""

from __future__ import annotations

from nexusos.indexing.ids import run_id


def test_run_ids_sort_in_creation_order() -> None:
    first = run_id()
    second = run_id()

    assert first < second

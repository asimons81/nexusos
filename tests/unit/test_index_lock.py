"""Unit tests for the workspace index lock."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path  # noqa: TC003

import pytest

from nexusos.core.errors import IndexLockConflictError, IndexLockError
from nexusos.indexing.lock import STALE_LOCK_TTL_SECONDS, IndexLock


def test_acquire_and_release(tmp_path: Path) -> None:
    lock = IndexLock(tmp_path / "index.lock")
    assert not lock.is_locked
    assert not lock.held
    lock.acquire(lock_run_id="nxo_run_test")
    assert lock.is_locked
    assert lock.held
    owner = json.loads((tmp_path / "index.lock").read_text(encoding="utf-8"))
    assert owner["pid"] == os.getpid()
    assert owner["run_id"] == "nxo_run_test"
    assert owner["started_at"]
    lock.release()
    assert not lock.is_locked
    assert not lock.held


def test_locked_context_manager(tmp_path: Path) -> None:
    lock = IndexLock(tmp_path / "index.lock")
    with lock.locked(lock_run_id="nxo_run_ctx"):
        assert lock.is_locked
        assert lock.held
    assert not lock.is_locked


def test_second_acquire_same_process_conflicts(tmp_path: Path) -> None:
    lock = IndexLock(tmp_path / "index.lock")
    lock.acquire()
    try:
        with pytest.raises(IndexLockConflictError):
            IndexLock(tmp_path / "index.lock").acquire()
    finally:
        lock.release()
    # After release the same lock is acquirable again.
    again = IndexLock(tmp_path / "index.lock")
    again.acquire()
    again.release()


def test_release_without_acquire_raises(tmp_path: Path) -> None:
    lock = IndexLock(tmp_path / "index.lock")
    with pytest.raises(IndexLockError):
        lock.release()


def test_double_acquire_same_instance_raises(tmp_path: Path) -> None:
    lock = IndexLock(tmp_path / "index.lock")
    lock.acquire()
    try:
        with pytest.raises(IndexLockError):
            lock.acquire()
    finally:
        lock.release()


def test_release_requires_owner_token(tmp_path: Path) -> None:
    lock = IndexLock(tmp_path / "index.lock")
    lock.acquire()
    path = tmp_path / "index.lock"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["token"] = "tampered"
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        with pytest.raises(IndexLockError):
            lock.release()
    finally:
        path.unlink(missing_ok=True)


def _dead_pid() -> int:
    """Spawn a short-lived child and return its PID once it has exited."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    pid = int(proc.stdout.readline().strip())
    proc.wait()
    return pid


def test_stale_lock_with_dead_pid_is_reclaimed(tmp_path: Path) -> None:
    path = tmp_path / "index.lock"
    path.write_text(
        json.dumps(
            {
                "pid": _dead_pid(),
                "host": "test",
                "started_at": "now",
                "run_id": "nxo_run_stale",
                "token": "dead",
            }
        ),
        encoding="utf-8",
    )
    lock = IndexLock(path)
    lock.acquire()
    assert lock.is_locked
    lock.release()


def test_live_pid_lock_conflicts_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "index.lock"
    script = (
        "import json, os, sys, time\n"
        "path = sys.argv[1]\n"
        "os.makedirs(os.path.dirname(path), exist_ok=True)\n"
        "with open(path, 'w') as f:\n"
        "    json.dump({'pid': os.getpid(), 'host': 'child', 'started_at': 'now',\n"
        "               'run_id': 'nxo_run_child', 'token': 'child'}, f)\n"
        "print('ready', flush=True)\n"
        "time.sleep(15)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        with pytest.raises(IndexLockConflictError):
            IndexLock(path).acquire()
    finally:
        proc.terminate()
        proc.wait()
    # Once the child is gone, the abandoned lock is reclaimed.
    lock = IndexLock(path)
    lock.acquire()
    assert lock.is_locked
    lock.release()


def test_corrupt_lock_fresh_conflicts_then_old_reclaimed(tmp_path: Path) -> None:
    path = tmp_path / "index.lock"
    path.write_text("not json {{{", encoding="utf-8")
    with pytest.raises(IndexLockConflictError):
        IndexLock(path).acquire()
    old = time.time() - STALE_LOCK_TTL_SECONDS - 10
    os.utime(path, (old, old))
    lock = IndexLock(path)
    lock.acquire()
    assert lock.is_locked
    lock.release()

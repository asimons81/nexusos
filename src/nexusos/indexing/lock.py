"""Cross-platform workspace index lock.

Allows many readers and one index writer. The lock is a JSON metadata file
under ``.nexusos/`` containing the owner PID, start timestamp, run ID, and an
ownership token. A lock owned by a living process is never deleted blindly; a
lock whose owner is dead (or whose metadata is unreadable and older than the
stale TTL) is reclaimed automatically.

Recovery contract: normal termination always releases the lock; a crashed
process leaves a stale lock that the next writer reclaims once the owning PID
is no longer alive.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import time
from collections.abc import Iterator  # noqa: TC003
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexusos.core.errors import IndexLockConflictError, IndexLockError

#: How long a lock with unreadable/corrupt metadata must be old before it is
#: considered abandoned and reclaimed (seconds).
STALE_LOCK_TTL_SECONDS = 300


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _pid_alive_windows(pid: int) -> bool:
    """Return process liveness on Windows without generating a console signal.

    ``os.kill(pid, 0)`` is a harmless existence probe on POSIX. On Windows,
    signal value 0 is ``CTRL_C_EVENT`` and can interrupt the test runner or
    another console process. Querying the process handle avoids that side
    effect while retaining the stale-lock recovery contract.
    """
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    access_denied = 5

    ctypes_namespace = vars(ctypes)
    win_dll: Any = ctypes_namespace["WinDLL"]
    get_last_error: Any = ctypes_namespace["get_last_error"]
    kernel32: Any = win_dll("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return int(get_last_error()) == access_denied

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            # A process we cannot query after opening should be treated as
            # alive. Never reclaim a lock based on an uncertain probe.
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    """Return True when the PID refers to a living process on this host."""
    if pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user — treat as alive (never blind-delete).
        return True
    except OSError:
        return False
    return True


def _lock_payload(token: str, lock_run_id: str | None) -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "host": platform.node(),
        "started_at": _iso_now(),
        "run_id": lock_run_id or "",
        "token": token,
    }


class IndexLock:
    """An exclusive writer lock for a NexusOS index database."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = Path(lock_path)
        self._token: str | None = None
        self._held_run_id: str | None = None

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def is_locked(self) -> bool:
        return self._lock_path.exists()

    @property
    def held(self) -> bool:
        return self._token is not None

    def acquire(self, *, lock_run_id: str | None = None) -> None:
        """Acquire the lock exclusively, reclaiming stale locks when safe."""
        if self.held:
            raise IndexLockError("index lock is already held by this instance")
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(8)
        payload = _lock_payload(token, lock_run_id)
        try:
            self._write_new(payload)
        except FileExistsError:
            if not self._reclaim_if_stale():
                owner = self._owner_description()
                raise IndexLockConflictError(f"index is locked by another process: {owner}")
            try:
                self._write_new(payload)
            except FileExistsError:
                raise IndexLockConflictError(
                    "index lock is contended; another process acquired it first"
                )
        self._token = token
        self._held_run_id = lock_run_id

    def release(self) -> None:
        """Release the lock. Only the owning instance may release it."""
        if not self.held:
            raise IndexLockError("index lock is not held by this instance")
        try:
            data = json.loads(self._lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Lock file is already gone or unreadable — nothing left to remove.
            self._token = None
            return
        if data.get("token") != self._token:
            raise IndexLockError("cannot release index lock: ownership token does not match")
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError as exc:
            raise IndexLockError(f"cannot remove index lock {self._lock_path}: {exc}")
        self._token = None

    @contextmanager
    def locked(self, *, lock_run_id: str | None = None) -> Iterator[None]:
        """Context manager that acquires the lock and always releases it."""
        self.acquire(lock_run_id=lock_run_id)
        try:
            yield
        finally:
            self.release()

    def _write_new(self, payload: dict[str, Any]) -> None:
        fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _read_owner(self) -> dict[str, Any] | None:
        try:
            data: Any = json.loads(self._lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _reclaim_if_stale(self) -> bool:
        """Remove the lock file when the owner is dead or clearly abandoned."""
        owner = self._read_owner()
        if owner is not None and isinstance(owner.get("pid"), int) and owner["pid"] > 0:
            pid = int(owner["pid"])
            if _pid_alive(pid):
                return False  # owned by a living process — never blind-delete
            self._lock_path.unlink(missing_ok=True)
            return True
        # Unreadable/corrupt metadata: reclaim only when old enough.
        try:
            age = time.time() - self._lock_path.stat().st_mtime
        except OSError:
            return False
        if age > STALE_LOCK_TTL_SECONDS:
            self._lock_path.unlink(missing_ok=True)
            return True
        return False

    def _owner_description(self) -> str:
        owner = self._read_owner()
        if owner is None:
            return f"lock file {self._lock_path} is present but unreadable"
        pid = owner.get("pid")
        run = owner.get("run_id")
        parts = []
        if isinstance(pid, int):
            parts.append(f"pid {pid}")
        if run:
            parts.append(f"run {run}")
        if owner.get("started_at"):
            parts.append(f"since {owner['started_at']}")
        detail = ", ".join(parts) if parts else "metadata unavailable"
        return f"{detail} ({self._lock_path})"

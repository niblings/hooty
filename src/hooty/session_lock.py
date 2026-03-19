"""Session locking to prevent concurrent access.

Uses fcntl.flock() on POSIX for race-free locking, with a PID-based
fallback on Windows where fcntl is unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.config import AppConfig

try:
    import fcntl

    _USE_FLOCK = True
except ImportError:
    _USE_FLOCK = False

# File descriptors held for active flock locks (session_id -> fd).
_held_locks: dict[str, int] = {}


def _lock_path(config: AppConfig, session_id: str) -> Path:
    """Return the lock file path for a session."""
    return config.locks_dir / f"{session_id}.lock"


def _pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# flock-based implementation (POSIX)
# ---------------------------------------------------------------------------


def _flock_acquire(config: AppConfig, session_id: str) -> bool:
    lock_file = _lock_path(config, session_id)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    if session_id in _held_locks:
        return True  # already held by us

    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        os.close(fd)
        return False

    # Write PID for diagnostics
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, str(os.getpid()).encode())

    _held_locks[session_id] = fd
    return True


def _flock_release(config: AppConfig, session_id: str) -> None:
    fd = _held_locks.pop(session_id, None)
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except OSError:
        pass
    lock_file = _lock_path(config, session_id)
    try:
        lock_file.unlink()
    except OSError:
        pass


def _flock_is_locked(config: AppConfig, session_id: str) -> bool:
    if session_id in _held_locks:
        return False  # held by us

    lock_file = _lock_path(config, session_id)
    if not lock_file.exists():
        return False

    try:
        fd = os.open(str(lock_file), os.O_RDWR, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Got the lock → not held by anyone
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except (OSError, BlockingIOError):
        return True
    finally:
        os.close(fd)


def _flock_cleanup(config: AppConfig) -> int:
    locks_dir = config.locks_dir
    if not locks_dir.exists():
        return 0

    removed = 0
    for lock_file in locks_dir.glob("*.lock"):
        sid = lock_file.stem
        if sid in _held_locks:
            continue
        try:
            fd = os.open(str(lock_file), os.O_RDWR, 0o644)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Got the lock → stale
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            try:
                lock_file.unlink()
                removed += 1
            except OSError:
                pass
        except (OSError, BlockingIOError):
            # Held by another process → alive
            os.close(fd)

    return removed


# ---------------------------------------------------------------------------
# PID-based fallback (Windows)
# ---------------------------------------------------------------------------


def _pid_acquire(config: AppConfig, session_id: str) -> bool:
    lock_file = _lock_path(config, session_id)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    my_pid = os.getpid()

    if lock_file.exists():
        try:
            existing_pid = int(lock_file.read_text().strip())
        except (ValueError, OSError):
            existing_pid = -1

        if existing_pid == my_pid:
            return True

        if _pid_alive(existing_pid):
            return False

    from hooty.concurrency import atomic_write_text

    atomic_write_text(lock_file, str(my_pid))
    return True


def _pid_release(config: AppConfig, session_id: str) -> None:
    lock_file = _lock_path(config, session_id)
    if not lock_file.exists():
        return
    try:
        existing_pid = int(lock_file.read_text().strip())
    except (ValueError, OSError):
        existing_pid = -1
    if existing_pid == os.getpid():
        try:
            lock_file.unlink()
        except OSError:
            pass


def _pid_is_locked(config: AppConfig, session_id: str) -> bool:
    lock_file = _lock_path(config, session_id)
    if not lock_file.exists():
        return False
    try:
        existing_pid = int(lock_file.read_text().strip())
    except (ValueError, OSError):
        return False
    if existing_pid == os.getpid():
        return False
    return _pid_alive(existing_pid)


def _pid_cleanup(config: AppConfig) -> int:
    locks_dir = config.locks_dir
    if not locks_dir.exists():
        return 0

    removed = 0
    my_pid = os.getpid()
    for lock_file in locks_dir.glob("*.lock"):
        try:
            pid = int(lock_file.read_text().strip())
        except (ValueError, OSError):
            try:
                lock_file.unlink()
                removed += 1
            except OSError:
                pass
            continue

        if pid == my_pid:
            continue

        if not _pid_alive(pid):
            try:
                lock_file.unlink()
                removed += 1
            except OSError:
                pass

    return removed


# ---------------------------------------------------------------------------
# Public API — dispatches to flock or PID implementation
# ---------------------------------------------------------------------------


def acquire_lock(config: AppConfig, session_id: str) -> bool:
    """Acquire a lock for *session_id*.

    Returns ``True`` on success, ``False`` if another live process holds the
    lock.
    """
    if _USE_FLOCK:
        return _flock_acquire(config, session_id)
    return _pid_acquire(config, session_id)


def release_lock(config: AppConfig, session_id: str) -> None:
    """Release the lock for *session_id*."""
    if _USE_FLOCK:
        _flock_release(config, session_id)
    else:
        _pid_release(config, session_id)


def is_locked(config: AppConfig, session_id: str) -> bool:
    """Return ``True`` if *session_id* is locked by another live process."""
    if _USE_FLOCK:
        return _flock_is_locked(config, session_id)
    return _pid_is_locked(config, session_id)


def cleanup_stale_locks(config: AppConfig) -> int:
    """Remove lock files whose owning process is dead.

    Returns the number of stale locks removed.
    """
    if _USE_FLOCK:
        return _flock_cleanup(config)
    return _pid_cleanup(config)

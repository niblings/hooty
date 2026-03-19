"""Tests for session locking (flock + PID fallback)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from hooty.config import AppConfig
from hooty.session_lock import (
    _USE_FLOCK,
    _held_locks,
    _pid_alive,
    acquire_lock,
    cleanup_stale_locks,
    is_locked,
    release_lock,
)


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    """Create a config with a temp config_dir."""
    cfg = AppConfig()
    cfg.__class__ = type("_TmpConfig", (AppConfig,), {
        "config_dir": property(lambda self: tmp_path),
    })
    return cfg


@pytest.fixture(autouse=True)
def _cleanup_held_locks():
    """Clean up held flock file descriptors between tests."""
    yield
    for sid, fd in list(_held_locks.items()):
        try:
            os.close(fd)
        except OSError:
            pass
    _held_locks.clear()


class TestPidAlive:
    """Test PID liveness detection."""

    def test_current_process_is_alive(self):
        assert _pid_alive(os.getpid()) is True

    def test_zero_pid_is_not_alive(self):
        assert _pid_alive(0) is False

    def test_negative_pid_is_not_alive(self):
        assert _pid_alive(-1) is False

    def test_nonexistent_pid(self):
        # PID 4000000 is very unlikely to exist
        assert _pid_alive(4000000) is False


class TestAcquireLock:
    """Test lock acquisition."""

    def test_acquire_new_lock(self, config: AppConfig):
        assert acquire_lock(config, "session-1") is True
        lock_file = config.locks_dir / "session-1.lock"
        assert lock_file.exists()
        assert lock_file.read_text().strip() == str(os.getpid())

    def test_acquire_same_lock_twice(self, config: AppConfig):
        assert acquire_lock(config, "session-1") is True
        assert acquire_lock(config, "session-1") is True

    def test_acquire_lock_stale_file(self, config: AppConfig):
        """A lock file from a dead process should be reclaimable."""
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"
        lock_file.write_text("4000000")  # non-existent PID, no flock held

        assert acquire_lock(config, "session-1") is True
        assert lock_file.read_text().strip() == str(os.getpid())

    @pytest.mark.skipif(not _USE_FLOCK, reason="flock not available")
    def test_acquire_lock_held_by_flock(self, config: AppConfig):
        """Cannot acquire a lock that's held via flock by another fd."""
        import fcntl

        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"

        # Simulate another process holding the lock
        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, b"99999")
        try:
            assert acquire_lock(config, "session-1") is False
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @pytest.mark.skipif(_USE_FLOCK, reason="PID fallback only")
    def test_acquire_lock_held_by_live_process_pid(self, config: AppConfig):
        """PID fallback: cannot acquire lock held by a live PID."""
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"
        lock_file.write_text("1")

        with patch("hooty.session_lock._pid_alive", return_value=True):
            assert acquire_lock(config, "session-1") is False

    def test_acquire_lock_corrupt_file(self, config: AppConfig):
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"
        lock_file.write_text("not-a-number")

        assert acquire_lock(config, "session-1") is True

    def test_creates_locks_directory(self, config: AppConfig):
        assert not config.locks_dir.exists()
        acquire_lock(config, "session-1")
        assert config.locks_dir.exists()


class TestReleaseLock:
    """Test lock release."""

    def test_release_own_lock(self, config: AppConfig):
        acquire_lock(config, "session-1")
        lock_file = config.locks_dir / "session-1.lock"
        assert lock_file.exists()

        release_lock(config, "session-1")
        assert not lock_file.exists()

    def test_release_nonexistent_lock(self, config: AppConfig):
        # Should not raise
        release_lock(config, "no-such-session")

    def test_does_not_release_other_process_lock(self, config: AppConfig):
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"
        lock_file.write_text("99999")

        release_lock(config, "session-1")
        # Lock should still exist (not in _held_locks / belongs to another PID)
        assert lock_file.exists()


class TestIsLocked:
    """Test lock status checking."""

    def test_not_locked_when_no_file(self, config: AppConfig):
        assert is_locked(config, "session-1") is False

    def test_not_locked_when_own_process(self, config: AppConfig):
        acquire_lock(config, "session-1")
        assert is_locked(config, "session-1") is False

    @pytest.mark.skipif(not _USE_FLOCK, reason="flock not available")
    def test_locked_by_flock(self, config: AppConfig):
        """A lock held via flock appears locked."""
        import fcntl

        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            assert is_locked(config, "session-1") is True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @pytest.mark.skipif(_USE_FLOCK, reason="PID fallback only")
    def test_locked_by_live_process_pid(self, config: AppConfig):
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"
        lock_file.write_text("1")

        with patch("hooty.session_lock._pid_alive", return_value=True):
            assert is_locked(config, "session-1") is True

    def test_not_locked_by_dead_process(self, config: AppConfig):
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"
        lock_file.write_text("4000000")

        assert is_locked(config, "session-1") is False

    def test_corrupt_lock_file(self, config: AppConfig):
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "session-1.lock"
        lock_file.write_text("garbage")

        assert is_locked(config, "session-1") is False


class TestCleanupStaleLocks:
    """Test stale lock cleanup."""

    def test_no_locks_dir(self, config: AppConfig):
        assert cleanup_stale_locks(config) == 0

    def test_removes_stale_locks(self, config: AppConfig):
        """Lock files with no flock held (or dead PID) are removed."""
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        (config.locks_dir / "dead-1.lock").write_text("4000000")
        (config.locks_dir / "dead-2.lock").write_text("4000001")

        removed = cleanup_stale_locks(config)
        assert removed == 2
        assert not (config.locks_dir / "dead-1.lock").exists()
        assert not (config.locks_dir / "dead-2.lock").exists()

    def test_keeps_own_locks(self, config: AppConfig):
        acquire_lock(config, "my-session")
        removed = cleanup_stale_locks(config)
        assert removed == 0
        assert (config.locks_dir / "my-session.lock").exists()

    @pytest.mark.skipif(not _USE_FLOCK, reason="flock not available")
    def test_keeps_flock_held_locks(self, config: AppConfig):
        """Locks held by flock are not removed."""
        import fcntl

        config.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = config.locks_dir / "other.lock"

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            removed = cleanup_stale_locks(config)
            assert removed == 0
            assert lock_file.exists()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @pytest.mark.skipif(_USE_FLOCK, reason="PID fallback only")
    def test_keeps_live_process_locks_pid(self, config: AppConfig):
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        (config.locks_dir / "other.lock").write_text("1")

        with patch("hooty.session_lock._pid_alive", return_value=True):
            removed = cleanup_stale_locks(config)
        assert removed == 0
        assert (config.locks_dir / "other.lock").exists()

    def test_removes_corrupt_locks(self, config: AppConfig):
        config.locks_dir.mkdir(parents=True, exist_ok=True)
        (config.locks_dir / "corrupt.lock").write_text("not-a-pid")

        removed = cleanup_stale_locks(config)
        assert removed == 1
        assert not (config.locks_dir / "corrupt.lock").exists()

    def test_mixed_locks(self, config: AppConfig):
        """Own locks kept, stale and corrupt locks removed."""
        # Acquire our lock properly
        acquire_lock(config, "mine")
        # Stale lock (dead PID, no flock)
        (config.locks_dir / "dead.lock").write_text("4000000")
        # Corrupt lock
        (config.locks_dir / "bad.lock").write_text("xyz")

        removed = cleanup_stale_locks(config)
        assert removed == 2
        assert (config.locks_dir / "mine.lock").exists()


class TestMultiprocessLocking:
    """Test that locking works across processes."""

    @pytest.mark.skipif(not _USE_FLOCK, reason="flock not available")
    def test_two_processes_same_session(self, config: AppConfig):
        """Only one process should acquire the lock."""
        import multiprocessing

        lock_dir = config.locks_dir
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / "shared.lock"

        def child_acquire(result_queue, lock_path_str):
            """Child process: try to acquire flock."""
            import fcntl
            try:
                fd = os.open(lock_path_str, os.O_RDWR | os.O_CREAT, 0o644)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    result_queue.put(True)
                    # Hold the lock briefly
                    import time
                    time.sleep(0.5)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except (OSError, BlockingIOError):
                    result_queue.put(False)
                finally:
                    os.close(fd)
            except Exception:
                result_queue.put(False)

        # Parent acquires first
        assert acquire_lock(config, "shared") is True

        # Child should fail
        q: multiprocessing.Queue = multiprocessing.Queue()
        p = multiprocessing.Process(target=child_acquire, args=(q, str(lock_file)))
        p.start()
        p.join(timeout=5)
        child_got_lock = q.get(timeout=1)
        assert child_got_lock is False

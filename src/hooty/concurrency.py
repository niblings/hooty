"""Concurrency utilities — WAL-mode SQLite engines and atomic file writes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sqlalchemy import Engine, event
from sqlalchemy import create_engine


def create_wal_engine(db_path: str) -> Engine:
    """Create a SQLAlchemy Engine with WAL mode and appropriate timeouts.

    Enables concurrent read/write access from multiple processes.
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Atomically write text to a file using rename.

    Writes to a temporary file in the same directory, then replaces
    the target via os.replace() (atomic on POSIX).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write bytes to a file using rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

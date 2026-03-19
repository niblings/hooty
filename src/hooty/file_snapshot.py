"""File snapshot store for tracking session file changes."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hooty")

_NEW_FILE_SENTINEL = "__NEW_FILE__"


@dataclass
class FileChange:
    """A single file change tracked during the session."""

    path: str  # absolute path
    status: str  # "created" | "modified" | "deleted"
    original: str | None  # snapshot content (None for binary/new)
    current: str | None  # current content (None for binary/deleted)
    externally_modified: bool  # last_hash != current hash


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _encode_key(abs_path: str) -> str:
    """Base64url-encode an absolute path for use as a filename."""
    return base64.urlsafe_b64encode(abs_path.encode()).decode().rstrip("=")


class FileSnapshotStore:
    """Track file snapshots for a session.

    Stores original file contents before LLM modifications and records
    post-write hashes for external change detection.
    """

    def __init__(self, session_dir: Path) -> None:
        self._dir = session_dir / "snapshots"
        self._index_path = self._dir / "_index.json"
        self._index: dict[str, dict] = {}  # abs_path -> {"snapshot": str, "last_hash": str}
        self._load_index()

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._index = {}

    def _save_index(self) -> None:
        from hooty.concurrency import atomic_write_text

        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._index_path,
            json.dumps(self._index, ensure_ascii=False, indent=2),
        )

    def capture_before_write(self, resolved_path: Path) -> None:
        """Capture original file content before the first modification.

        For new files (not yet existing), stores a sentinel value.
        Subsequent calls for the same path are no-ops.
        """
        abs_path = str(resolved_path)
        if abs_path in self._index:
            return  # already captured

        self._dir.mkdir(parents=True, exist_ok=True)
        snapshot_name = _encode_key(abs_path)
        snapshot_file = self._dir / snapshot_name

        if resolved_path.exists():
            try:
                data = resolved_path.read_bytes()
                snapshot_file.write_bytes(data)
            except OSError as e:
                logger.debug("snapshot: failed to capture %s: %s", abs_path, e)
                return
        else:
            # New file — write sentinel
            snapshot_file.write_text(_NEW_FILE_SENTINEL, encoding="utf-8")

        self._index[abs_path] = {"snapshot": snapshot_name, "last_hash": ""}
        self._save_index()

    def record_after_write(self, resolved_path: Path) -> None:
        """Record the file's SHA-256 hash after a successful write/edit."""
        abs_path = str(resolved_path)
        entry = self._index.get(abs_path)
        if entry is None:
            return

        try:
            entry["last_hash"] = _file_hash(resolved_path)
        except OSError:
            entry["last_hash"] = ""
        self._save_index()

    def get_changes(self) -> list[FileChange]:
        """Return list of file changes in this session."""
        changes: list[FileChange] = []
        for abs_path, entry in list(self._index.items()):
            snapshot_file = self._dir / entry["snapshot"]
            resolved = Path(abs_path)

            # Read original content
            is_new = False
            original_bytes: bytes | None = None
            if snapshot_file.exists():
                raw = snapshot_file.read_bytes()
                if raw == _NEW_FILE_SENTINEL.encode("utf-8"):
                    is_new = True
                else:
                    original_bytes = raw

            # Read current content
            current_exists = resolved.exists()
            current_bytes: bytes | None = None
            if current_exists:
                try:
                    current_bytes = resolved.read_bytes()
                except OSError:
                    pass

            # Determine status
            if is_new and not current_exists:
                status = "deleted"  # created then deleted
            elif is_new:
                status = "created"
            elif not current_exists:
                status = "deleted"
            else:
                status = "modified"

            # Decode text (None for binary)
            original = _safe_decode(original_bytes) if original_bytes is not None else None
            current = _safe_decode(current_bytes) if current_bytes is not None else None

            # Check external modification
            externally_modified = False
            if current_exists and entry.get("last_hash"):
                try:
                    current_hash = _file_hash(resolved)
                    externally_modified = current_hash != entry["last_hash"]
                except OSError:
                    pass

            # Skip if unchanged (original == current)
            if status == "modified" and original_bytes is not None and current_bytes is not None:
                if original_bytes == current_bytes:
                    continue

            # Skip created-then-deleted with no content
            if is_new and not current_exists:
                continue

            changes.append(FileChange(
                path=abs_path,
                status=status,
                original=original,
                current=current,
                externally_modified=externally_modified,
            ))

        return changes

    def restore(self, abs_path: str) -> bool:
        """Restore a file to its original state. Returns True on success."""
        entry = self._index.get(abs_path)
        if entry is None:
            return False

        snapshot_file = self._dir / entry["snapshot"]
        resolved = Path(abs_path)

        if not snapshot_file.exists():
            return False

        raw = snapshot_file.read_bytes()

        if raw == _NEW_FILE_SENTINEL.encode("utf-8"):
            # File was created during session — delete it
            if resolved.exists():
                resolved.unlink()
        else:
            # Restore original content
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_bytes(raw)

        self.remove_entry(abs_path)
        return True

    def remove_entry(self, abs_path: str) -> None:
        """Remove an entry from the index and delete its snapshot file."""
        entry = self._index.pop(abs_path, None)
        if entry is None:
            return
        snapshot_file = self._dir / entry["snapshot"]
        if snapshot_file.exists():
            try:
                snapshot_file.unlink()
            except OSError:
                pass
        self._save_index()


def _safe_decode(data: bytes) -> str | None:
    """Try to decode bytes as UTF-8. Returns None for binary content."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None

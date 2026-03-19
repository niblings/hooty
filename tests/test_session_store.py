"""Tests for session store helper functions for Hooty."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from hooty.config import AppConfig
from hooty.session_store import (
    cleanup_orphan_dirs,
    find_purgeable_sessions,
    format_session_for_display,
    get_most_recent_session_id,
    list_sessions,
    purge_sessions,
    session_exists,
)


class TestGetMostRecentSessionId:
    """Test finding the most recent session."""

    @patch("hooty.session_store._create_storage")
    def test_returns_none_when_no_sessions(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_db.get_sessions.return_value = ([], 0)
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        result = get_most_recent_session_id(config)

        assert result is None

    @patch("hooty.session_store._create_storage")
    def test_returns_most_recent_id(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_db.get_sessions.return_value = (
            [{"session_id": "abc-123-def"}],
            1,
        )
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        result = get_most_recent_session_id(config)

        assert result == "abc-123-def"
        mock_db.get_sessions.assert_called_once()
        call_kwargs = mock_db.get_sessions.call_args[1]
        assert call_kwargs["sort_by"] == "updated_at"
        assert call_kwargs["sort_order"] == "desc"
        assert call_kwargs["limit"] == 1


class TestListSessions:
    """Test listing sessions."""

    @patch("hooty.session_store._create_storage")
    def test_returns_empty_list(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_db.get_sessions.return_value = ([], 0)
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        sessions, total = list_sessions(config)

        assert sessions == []
        assert total == 0

    @patch("hooty.session_store._create_storage")
    def test_returns_sessions_sorted(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_db.get_sessions.return_value = (
            [{"session_id": "aaa"}, {"session_id": "bbb"}],
            2,
        )
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        sessions, total = list_sessions(config, limit=5)

        assert len(sessions) == 2
        assert total == 2
        call_kwargs = mock_db.get_sessions.call_args[1]
        assert call_kwargs["sort_by"] == "updated_at"
        assert call_kwargs["sort_order"] == "desc"
        assert call_kwargs["limit"] == 5


class TestSessionExists:
    """Test session existence check."""

    @patch("hooty.session_store._create_storage")
    def test_exists(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_db.get_session.return_value = {"session_id": "abc-123"}
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        assert session_exists(AppConfig(), "abc-123") is True

    @patch("hooty.session_store._create_storage")
    def test_not_exists(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_db.get_session.return_value = None
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        assert session_exists(AppConfig(), "nonexistent") is False


class TestFormatSessionForDisplay:
    """Test session display formatting."""

    def test_basic_formatting(self):
        raw = {
            "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "updated_at": 1740000000,
            "runs": [
                {"input": {"input_content": "hello world"}},
                {"input": {"input_content": "second message"}},
            ],
        }
        result = format_session_for_display(raw)

        assert result["short_id"] == "a1b2c3d4"
        assert result["session_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert result["run_count"] == "2"
        assert result["preview"] == "hello world"
        assert "2025" in result["updated_at"]

    def test_empty_runs(self):
        raw = {
            "session_id": "abcdef01-2345-6789-abcd-ef0123456789",
            "updated_at": 1740000000,
            "runs": [],
        }
        result = format_session_for_display(raw)

        assert result["run_count"] == "0"
        assert result["preview"] == ""

    def test_no_runs_key(self):
        raw = {
            "session_id": "abcdef01-2345-6789-abcd-ef0123456789",
            "created_at": 1740000000,
        }
        result = format_session_for_display(raw)

        assert result["run_count"] == "0"
        assert result["preview"] == ""

    def test_long_preview_truncated(self):
        raw = {
            "session_id": "abcdef01-2345-6789-abcd-ef0123456789",
            "updated_at": 1740000000,
            "runs": [
                {"input": {"input_content": "A" * 100}},
            ],
        }
        result = format_session_for_display(raw)

        assert len(result["preview"]) <= 50
        assert result["preview"].endswith("…")

    def test_fallback_to_messages(self):
        raw = {
            "session_id": "abcdef01-2345-6789-abcd-ef0123456789",
            "updated_at": 1740000000,
            "runs": [
                {
                    "input": {},
                    "messages": [
                        {"role": "system", "content": "You are an AI"},
                        {"role": "user", "content": "Help me"},
                    ],
                },
            ],
        }
        result = format_session_for_display(raw)

        assert result["preview"] == "Help me"

    def test_no_timestamp(self):
        raw = {"session_id": "abcdef01-2345-6789-abcd-ef0123456789"}
        result = format_session_for_display(raw)

        assert result["updated_at"] == "unknown"


# -- Purge / Cleanup --


class TestFindPurgeableSessions:
    """Test finding sessions eligible for purge."""

    @patch("hooty.session_store._create_storage")
    def test_returns_old_sessions(self, mock_storage_fn):
        mock_db = MagicMock()
        old_ts = time.time() - 100 * 86400  # 100 days ago
        new_ts = time.time() - 10 * 86400   # 10 days ago
        mock_db.get_sessions.return_value = (
            [
                {"session_id": "old-1", "updated_at": old_ts},
                {"session_id": "new-1", "updated_at": new_ts},
            ],
            2,
        )
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        result = find_purgeable_sessions(AppConfig(), days=90)
        ids = [s["session_id"] for s in result]
        assert "old-1" in ids
        assert "new-1" not in ids

    @patch("hooty.session_store._create_storage")
    def test_excludes_specified_ids(self, mock_storage_fn):
        mock_db = MagicMock()
        old_ts = time.time() - 100 * 86400
        mock_db.get_sessions.return_value = (
            [
                {"session_id": "old-1", "updated_at": old_ts},
                {"session_id": "old-2", "updated_at": old_ts},
            ],
            2,
        )
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        result = find_purgeable_sessions(
            AppConfig(), days=90, exclude_ids={"old-1"}
        )
        ids = [s["session_id"] for s in result]
        assert "old-1" not in ids
        assert "old-2" in ids

    @patch("hooty.session_store._create_storage")
    def test_empty_when_all_recent(self, mock_storage_fn):
        mock_db = MagicMock()
        new_ts = time.time() - 1 * 86400
        mock_db.get_sessions.return_value = (
            [{"session_id": "new-1", "updated_at": new_ts}],
            1,
        )
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        result = find_purgeable_sessions(AppConfig(), days=90)
        assert result == []

    @patch("hooty.session_store._create_storage")
    def test_uses_created_at_fallback(self, mock_storage_fn):
        mock_db = MagicMock()
        old_ts = time.time() - 100 * 86400
        mock_db.get_sessions.return_value = (
            [{"session_id": "old-1", "created_at": old_ts}],
            1,
        )
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        result = find_purgeable_sessions(AppConfig(), days=90)
        assert len(result) == 1


class TestPurgeSessions:
    """Test session purging."""

    @patch("hooty.session_store._create_storage")
    def test_deletes_db_records(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        removed = purge_sessions(config, ["sess-1", "sess-2"])

        assert removed == 2
        assert mock_db.delete_session.call_count == 2

    @patch("hooty.session_store._create_storage")
    def test_removes_session_directories(self, mock_storage_fn, tmp_path: Path):
        mock_db = MagicMock()
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        config.__class__ = type("_TmpConfig", (AppConfig,), {
            "config_dir": property(lambda self: tmp_path),
        })

        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "sess-1" / "tmp").mkdir(parents=True)
        (sessions_dir / "sess-2" / "tmp").mkdir(parents=True)

        purge_sessions(config, ["sess-1", "sess-2"])

        assert not (sessions_dir / "sess-1").exists()
        assert not (sessions_dir / "sess-2").exists()

    def test_empty_list_returns_zero(self):
        assert purge_sessions(AppConfig(), []) == 0

    @patch("hooty.session_store._create_storage")
    def test_handles_db_error_gracefully(self, mock_storage_fn):
        mock_db = MagicMock()
        mock_db.delete_session.side_effect = Exception("db error")
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        removed = purge_sessions(config, ["sess-1"])
        assert removed == 0


class TestCleanupOrphanDirs:
    """Test orphan directory cleanup."""

    @patch("hooty.session_store._create_storage")
    def test_removes_orphan_dirs(self, mock_storage_fn, tmp_path: Path):
        mock_db = MagicMock()
        mock_db.get_session.return_value = None  # No matching DB record
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        config.__class__ = type("_TmpConfig", (AppConfig,), {
            "config_dir": property(lambda self: tmp_path),
        })

        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "orphan-1").mkdir(parents=True)
        (sessions_dir / "orphan-2").mkdir(parents=True)

        removed = cleanup_orphan_dirs(config)
        assert removed == 2
        assert not (sessions_dir / "orphan-1").exists()
        assert not (sessions_dir / "orphan-2").exists()

    @patch("hooty.session_store._create_storage")
    def test_keeps_valid_dirs(self, mock_storage_fn, tmp_path: Path):
        mock_db = MagicMock()
        mock_db.get_session.return_value = {"session_id": "valid-1"}
        mock_storage_fn.return_value.__enter__ = lambda self: mock_db
        mock_storage_fn.return_value.__exit__ = lambda self, *args: None

        config = AppConfig()
        config.__class__ = type("_TmpConfig", (AppConfig,), {
            "config_dir": property(lambda self: tmp_path),
        })

        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "valid-1").mkdir(parents=True)

        removed = cleanup_orphan_dirs(config)
        assert removed == 0
        assert (sessions_dir / "valid-1").exists()

    def test_no_sessions_dir(self, tmp_path: Path):
        config = AppConfig()
        config.__class__ = type("_TmpConfig", (AppConfig,), {
            "config_dir": property(lambda self: tmp_path),
        })

        removed = cleanup_orphan_dirs(config)
        assert removed == 0

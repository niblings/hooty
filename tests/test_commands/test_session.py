"""Tests for /new, /fork commands and _switch_session() helper."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from hooty.repl import REPL, SLASH_COMMANDS


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

@dataclass
class _FakeSession:
    """Minimal stand-in for AgentSession."""
    session_id: str = ""
    agent_id: str | None = None
    user_id: str | None = None
    session_data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    agent_data: dict[str, Any] | None = None
    runs: list | None = None
    summary: Any = None


class _FakeDB:
    """In-memory session store."""

    def __init__(self) -> None:
        self.sessions: dict[str, _FakeSession] = {}

    def get_session(self, session_id: str, session_type: Any, **kw) -> _FakeSession | None:
        return self.sessions.get(session_id)

    def upsert_session(self, session: Any, **kw) -> Any:
        self.sessions[session.session_id] = session
        return session


def _make_repl(tmp_path: Path) -> REPL:
    """Build a REPL with heavy parts stubbed out."""
    cfg = MagicMock()
    cfg.session_id = str(uuid.uuid4())
    cfg.config_dir = tmp_path
    cfg.session_dir = tmp_path / "sessions" / cfg.session_id
    cfg.session_tmp_dir = cfg.session_dir / "tmp"
    cfg.session_plans_dir = cfg.session_dir / "plans"
    cfg.working_directory = str(tmp_path)
    cfg.auto_compact = False

    # Patch heavy init to skip prompt_toolkit, agent creation, etc.
    with (
        patch.object(REPL, "__init__", lambda self, *a, **kw: None),
    ):
        repl = REPL.__new__(REPL)

    # Wire up minimal state
    repl.config = cfg
    repl.session_id = cfg.session_id
    repl.plan_mode = False
    repl._agent_plan_mode = False
    repl._session_dir_created = False
    repl.running = True
    repl.console = MagicMock()
    repl.confirm_ref = [True]
    repl.auto_ref = [False]
    repl.auto_execute_ref = [False]
    repl.pending_plan_ref = [None]
    repl.enter_plan_ref = [False]
    repl.pending_reason_ref = [None]
    repl.pending_revise_ref = [False]
    repl._last_plan_file = None
    repl._last_response_text = ""
    repl._last_final_text = ""
    repl._pending_skill_message = None

    fake_db = _FakeDB()
    repl.agent = MagicMock()
    repl.agent.db = fake_db
    repl.agent.model = MagicMock()

    # session_stats
    repl.session_stats = MagicMock()

    # hooks
    repl._hooks_config = {}
    repl._loop = None

    # Build CommandContext for command handlers
    repl._cmd_ctx = repl._build_command_context()

    return repl


def _rebuild_ctx(repl: REPL) -> None:
    """Rebuild CommandContext so patched methods take effect."""
    repl._cmd_ctx = repl._build_command_context()


def _cmd_new(repl: REPL) -> None:
    """Call cmd_new via the command module."""
    from hooty.commands.session import cmd_new
    _rebuild_ctx(repl)
    cmd_new(repl._cmd_ctx)


def _cmd_fork(repl: REPL) -> None:
    """Call cmd_fork via the command module."""
    from hooty.commands.session import cmd_fork
    _rebuild_ctx(repl)
    cmd_fork(repl._cmd_ctx)


# ---------------------------------------------------------------------------
# _switch_session tests
# ---------------------------------------------------------------------------

class TestSwitchSession:
    """Tests for _switch_session() helper."""

    def test_success_saves_stats_and_switches(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        old_id = repl.session_id

        new_id = str(uuid.uuid4())

        with (
            patch("hooty.session_lock.release_lock") as mock_release,
            patch("hooty.session_lock.acquire_lock", return_value=True) as mock_acquire,
            patch("hooty.session_stats.save_persisted_stats") as mock_save,
            patch("hooty.session_stats.load_persisted_stats", return_value=MagicMock()),
            patch("hooty.session_stats.SessionStats"),
            patch.object(repl, "_create_agent", return_value=MagicMock()),
            patch.object(repl, "_ensure_session_dir"),
        ):
            # Point session_dir to an existing path so stats save fires
            repl.config.session_dir = tmp_path
            result = repl._switch_session(new_id)

        assert result is True
        assert repl.session_id == new_id
        assert repl.config.session_id == new_id
        mock_save.assert_called_once()
        mock_release.assert_called_once_with(repl.config, old_id)
        mock_acquire.assert_called_once_with(repl.config, new_id)

    def test_lock_failure_rolls_back(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        old_id = repl.session_id

        new_id = str(uuid.uuid4())

        with (
            patch("hooty.session_lock.release_lock"),
            patch("hooty.session_lock.acquire_lock", side_effect=[False, True]),
            patch("hooty.session_stats.save_persisted_stats"),
            patch.object(repl, "_ensure_session_dir"),
        ):
            repl.config.session_dir = tmp_path
            result = repl._switch_session(new_id)

        assert result is False
        # session_id should NOT have changed
        assert repl.session_id == old_id


# ---------------------------------------------------------------------------
# /new tests
# ---------------------------------------------------------------------------

class TestCmdNew:
    """Tests for cmd_new()."""

    def test_new_creates_fresh_session(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        old_id = repl.session_id

        with patch.object(repl, "_switch_session", return_value=True) as mock_switch:
            _cmd_new(repl)

        mock_switch.assert_called_once()
        call_arg = mock_switch.call_args[0][0]
        # Should be a valid UUID, different from old
        uuid.UUID(call_arg)  # raises on invalid
        assert call_arg != old_id

        # Should print success message
        repl.console.print.assert_called()
        msg = repl.console.print.call_args[0][0]
        assert "Started new session" in msg

    def test_new_lock_failure(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)

        with patch.object(repl, "_switch_session", return_value=False):
            _cmd_new(repl)

        msg = repl.console.print.call_args[0][0]
        assert "Could not acquire lock" in msg


# ---------------------------------------------------------------------------
# /fork tests
# ---------------------------------------------------------------------------

class TestCmdFork:
    """Tests for cmd_fork()."""

    def test_fork_empty_session(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        # Put an empty session in the fake DB
        repl.agent.db.sessions[repl.session_id] = _FakeSession(
            session_id=repl.session_id, runs=[], summary=None,
        )

        _cmd_fork(repl)

        msg = repl.console.print.call_args[0][0]
        assert "Nothing to fork" in msg

    def test_fork_session_not_in_db(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        # DB is empty — no session stored

        _cmd_fork(repl)

        msg = repl.console.print.call_args[0][0]
        assert "not found" in msg

    def test_fork_reuses_existing_summary(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        existing_summary = MagicMock()
        repl.agent.db.sessions[repl.session_id] = _FakeSession(
            session_id=repl.session_id,
            runs=[MagicMock()],
            summary=existing_summary,
            session_data={"working_directory": "/tmp"},
            agent_data={"name": "hooty"},
        )
        old_id = repl.session_id

        with patch.object(repl, "_switch_session", return_value=True):
            _cmd_fork(repl)

        # New session should have been upserted into DB
        new_sessions = {
            k: v for k, v in repl.agent.db.sessions.items() if k != old_id
        }
        assert len(new_sessions) == 1
        new_sess = list(new_sessions.values())[0]
        assert new_sess.summary is existing_summary
        assert new_sess.runs == []
        assert new_sess.session_data == {"working_directory": "/tmp"}

    def test_fork_generates_summary_when_missing(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        repl.agent.db.sessions[repl.session_id] = _FakeSession(
            session_id=repl.session_id,
            runs=[MagicMock()],
            summary=None,
        )

        generated = MagicMock()

        def fake_create(session):
            session.summary = generated

        with (
            patch(
                "agno.session.summary.SessionSummaryManager",
                return_value=MagicMock(create_session_summary=fake_create),
            ),
            patch.object(repl, "_switch_session", return_value=True),
        ):
            _cmd_fork(repl)

        # The new session should have the generated summary
        new_sessions = {
            k: v for k, v in repl.agent.db.sessions.items()
            if k != repl.session_id
        }
        new_sess = list(new_sessions.values())[0]
        assert new_sess.summary is generated

    def test_fork_continues_when_summary_generation_fails(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        repl.agent.db.sessions[repl.session_id] = _FakeSession(
            session_id=repl.session_id,
            runs=[MagicMock()],
            summary=None,
        )

        def fail_create(session):
            raise RuntimeError("LLM API error")

        with (
            patch(
                "agno.session.summary.SessionSummaryManager",
                return_value=MagicMock(create_session_summary=fail_create),
            ),
            patch.object(repl, "_switch_session", return_value=True),
        ):
            _cmd_fork(repl)

        # Should still fork (without summary) and print success
        calls = [str(c) for c in repl.console.print.call_args_list]
        assert any("Forking without summary" in c for c in calls)
        assert any("Forked session" in c for c in calls)

    def test_fork_does_not_modify_source(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        original_runs = [MagicMock()]
        source = _FakeSession(
            session_id=repl.session_id,
            runs=original_runs,
            summary=MagicMock(),
            session_data={"k": "v"},
        )
        repl.agent.db.sessions[repl.session_id] = source

        with patch.object(repl, "_switch_session", return_value=True):
            _cmd_fork(repl)

        # Source session object should be unchanged
        assert source.runs is original_runs
        assert len(source.runs) == 1

    def test_fork_does_not_copy_plans(self, tmp_path: Path) -> None:
        """Plans are project-scoped so fork should not copy them."""
        repl = _make_repl(tmp_path)
        repl.agent.db.sessions[repl.session_id] = _FakeSession(
            session_id=repl.session_id,
            runs=[MagicMock()],
            summary=MagicMock(),
        )

        # Create plans dir with a file
        plans = tmp_path / "sessions" / repl.session_id / "plans"
        plans.mkdir(parents=True)
        (plans / "design.md").write_text("# Design", encoding="utf-8")

        new_ids: list[str] = []

        def capture_switch(new_id: str) -> bool:
            new_ids.append(new_id)
            return True

        with patch.object(repl, "_switch_session", side_effect=capture_switch):
            _cmd_fork(repl)

        assert len(new_ids) == 1
        new_plans = tmp_path / "sessions" / new_ids[0] / "plans"
        assert not new_plans.exists()

    def test_fork_lock_failure(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        repl.agent.db.sessions[repl.session_id] = _FakeSession(
            session_id=repl.session_id,
            runs=[MagicMock()],
            summary=MagicMock(),
        )

        with patch.object(repl, "_switch_session", return_value=False):
            _cmd_fork(repl)

        msg = repl.console.print.call_args[0][0]
        assert "Could not acquire lock" in msg


# ---------------------------------------------------------------------------
# Command registration tests
# ---------------------------------------------------------------------------

class TestCommandRegistration:
    """Verify /clear removed, /new and /fork added."""

    def test_no_clear_in_slash_commands(self) -> None:
        names = [c[0] for c in SLASH_COMMANDS]
        assert "/clear" not in names

    def test_new_in_slash_commands(self) -> None:
        names = [c[0] for c in SLASH_COMMANDS]
        assert "/new" in names

    def test_fork_in_slash_commands(self) -> None:
        names = [c[0] for c in SLASH_COMMANDS]
        assert "/fork" in names

    def test_handlers_dispatch_new_and_fork(self) -> None:
        """Verify /new and /fork are in the dispatch table."""
        from hooty.commands.session import cmd_fork, cmd_new

        assert callable(cmd_new)
        assert callable(cmd_fork)

    def test_no_cmd_clear_method(self) -> None:
        assert not hasattr(REPL, "_cmd_clear")

"""Tests for confirmation dialog utilities."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from hooty.tools.confirm import (
    _active_live,
    _auto_approve,
    _confirm_action,
)


class TestActiveLive:
    """Test _active_live shared state."""

    def test_initial_value_is_none(self):
        assert _active_live[0] is None

    def test_is_mutable_list(self):
        assert isinstance(_active_live, list)
        assert len(_active_live) == 1


class TestConfirmAction:
    """Test _confirm_action using hotkey_select mock."""

    def setup_method(self):
        _auto_approve[0] = False

    def _call(self, hotkey_return: str | None) -> bool:
        """Helper: call _confirm_action with mocked hotkey_select."""
        with patch("hooty.tools.confirm.hotkey_select", return_value=hotkey_return):
            return _confirm_action("test action")

    def test_returns_true_on_yes(self):
        assert self._call("Y") is True

    def test_returns_false_on_no(self):
        assert self._call("N") is False

    def test_returns_false_on_none(self):
        assert self._call(None) is False

    def test_quit_raises_keyboard_interrupt(self):
        with pytest.raises(KeyboardInterrupt):
            self._call("Q")

    def test_all_sets_auto_approve(self):
        assert self._call("A") is True
        assert _auto_approve[0] is True

    def test_auto_approve_skips_prompt(self):
        _auto_approve[0] = True
        # hotkey_select should not be called
        with patch("hooty.tools.confirm.hotkey_select") as mock_hs:
            result = _confirm_action("test action")
        assert result is True
        mock_hs.assert_not_called()

    def test_live_stop_and_start(self):
        mock_live = MagicMock()
        with (
            patch("hooty.tools.confirm._active_live", [mock_live]),
            patch("hooty.tools.confirm.hotkey_select", return_value="Y"),
        ):
            result = _confirm_action("test action")

        assert result is True
        mock_live.stop.assert_called_once()
        mock_live.start.assert_called_once()

    def test_live_resumed_on_exception(self):
        mock_live = MagicMock()
        with (
            patch("hooty.tools.confirm._active_live", [mock_live]),
            patch("hooty.tools.confirm.hotkey_select", return_value="Q"),
        ):
            with pytest.raises(KeyboardInterrupt):
                _confirm_action("test action")

        mock_live.stop.assert_called_once()
        mock_live.start.assert_called_once()


class TestConfirmLockSerialization:
    """Test that _confirm_lock serialises concurrent calls."""

    def setup_method(self):
        _auto_approve[0] = False

    def test_concurrent_calls_are_serialised(self):
        """Two threads calling _confirm_action should not overlap."""
        call_order: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def fake_hotkey_select(*_args, **_kwargs):
            call_order.append("enter")
            # Signal that we're inside, then wait for the other thread
            # If serialised, the other thread won't reach here simultaneously.
            barrier.wait(timeout=2)
            call_order.append("exit")
            return "Y"

        # Because the lock serialises, only one thread enters at a time.
        # The barrier with 2 parties will timeout if calls are serialised
        # (the second thread is blocked on the lock).
        # We catch BrokenBarrierError to confirm serialisation.
        results: list[bool | Exception] = [None, None]  # type: ignore[list-item]

        def worker(idx: int):
            try:
                with patch(
                    "hooty.tools.confirm.hotkey_select",
                    side_effect=fake_hotkey_select,
                ):
                    results[idx] = _confirm_action(f"action-{idx}")
            except Exception as exc:
                results[idx] = exc

        t0 = threading.Thread(target=worker, args=(0,))
        t1 = threading.Thread(target=worker, args=(1,))
        t0.start()
        t1.start()
        t0.join(timeout=10)
        t1.join(timeout=10)

        # One thread should have hit BrokenBarrierError because the lock
        # prevented both from being inside hotkey_select simultaneously.
        barrier_errors = [r for r in results if isinstance(r, threading.BrokenBarrierError)]
        assert len(barrier_errors) == 1, (
            "Expected exactly one BrokenBarrierError proving serialisation"
        )

    def test_all_skips_subsequent_dialog(self):
        """After one thread selects 'A', the next skips the dialog."""
        call_count = 0
        gate = threading.Event()

        def fake_hotkey_first(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            gate.set()  # signal that first dialog is answered
            return "A"

        def fake_hotkey_second(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            return "Y"

        results: list[bool | None] = [None, None]

        def first():
            with patch(
                "hooty.tools.confirm.hotkey_select",
                side_effect=fake_hotkey_first,
            ):
                results[0] = _confirm_action("first")

        def second():
            gate.wait(timeout=5)  # ensure first completes
            with patch(
                "hooty.tools.confirm.hotkey_select",
                side_effect=fake_hotkey_second,
            ):
                results[1] = _confirm_action("second")

        t0 = threading.Thread(target=first)
        t1 = threading.Thread(target=second)
        t0.start()
        t1.start()
        t0.join(timeout=10)
        t1.join(timeout=10)

        assert results == [True, True]
        # hotkey_select should have been called only once (for the first thread)
        assert call_count == 1

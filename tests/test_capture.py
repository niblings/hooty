"""Tests for capture module and /attach capture command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hooty.attachment import Attachment
from hooty.capture import (
    CaptureResult,
    _MacWindow,
    _capture_macos,
    _list_macos_windows,
    _resolve_macos_target,
    _strip_app_suffix,
    is_capture_available,
    is_wsl2,
    sanitize_target_name,
)
from hooty.commands.attach import _format_image_info, _parse_capture_args


# --- sanitize_target_name ---


class TestSanitizeTargetName:
    def test_active(self):
        assert sanitize_target_name("active") == "active"

    def test_process_name(self):
        assert sanitize_target_name("chrome.exe") == "chrome.exe"

    def test_quoted_title(self):
        assert sanitize_target_name('"Design Doc"') == "design_doc"

    def test_special_characters(self):
        assert sanitize_target_name("my<file>:name") == "my_file_name"

    def test_spaces(self):
        assert sanitize_target_name("hello world") == "hello_world"

    def test_empty(self):
        assert sanitize_target_name("") == "unknown"

    def test_only_quotes(self):
        assert sanitize_target_name('""') == "unknown"


# --- _parse_capture_args ---


class TestParseCaptureArgs:
    def test_no_args(self):
        target, delay, repeat, interval = _parse_capture_args([])
        assert target == "active"
        assert delay == 0
        assert repeat == 1
        assert interval == 0

    def test_target_only(self):
        target, delay, repeat, interval = _parse_capture_args(["chrome.exe"])
        assert target == "chrome.exe"
        assert delay == 0

    def test_monitor_number(self):
        target, delay, repeat, interval = _parse_capture_args(["0"])
        assert target == "0"

    def test_primary(self):
        target, delay, repeat, interval = _parse_capture_args(["primary"])
        assert target == "primary"

    def test_delay(self):
        target, delay, repeat, interval = _parse_capture_args(["--delay", "5"])
        assert target == "active"
        assert delay == 5

    def test_target_with_delay(self):
        target, delay, repeat, interval = _parse_capture_args(
            ["chrome.exe", "--delay", "3"]
        )
        assert target == "chrome.exe"
        assert delay == 3

    def test_repeat_and_interval(self):
        target, delay, repeat, interval = _parse_capture_args(
            ["--repeat", "3", "--interval", "5"]
        )
        assert repeat == 3
        assert interval == 5

    def test_all_options(self):
        target, delay, repeat, interval = _parse_capture_args(
            ["chrome.exe", "--delay", "2", "--repeat", "3", "--interval", "10"]
        )
        assert target == "chrome.exe"
        assert delay == 2
        assert repeat == 3
        assert interval == 10

    def test_quoted_title(self):
        target, delay, repeat, interval = _parse_capture_args(
            ['"Design', 'Doc"']
        )
        assert target == "Design Doc"

    def test_invalid_delay_value(self):
        target, delay, repeat, interval = _parse_capture_args(["--delay", "abc"])
        assert delay == 0  # falls back to default


# --- is_capture_available ---


class TestIsCaptureAvailable:
    @patch("hooty.capture.sys")
    def test_windows(self, mock_sys):
        mock_sys.platform = "win32"
        assert is_capture_available() is True

    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    @patch("hooty.capture.sys")
    def test_macos(self, mock_sys, _mock_which):
        mock_sys.platform = "darwin"
        assert is_capture_available() is True

    @patch("hooty.capture.shutil.which", return_value=None)
    @patch("hooty.capture.sys")
    def test_macos_no_screencapture(self, mock_sys, _mock_which):
        mock_sys.platform = "darwin"
        assert is_capture_available() is False

    @patch("hooty.capture.sys")
    @patch("hooty.capture.Path")
    def test_wsl2(self, mock_path, mock_sys):
        mock_sys.platform = "linux"
        mock_path.return_value.read_text.return_value = (
            "Linux version 5.15.90.1-microsoft-standard-WSL2"
        )
        assert is_capture_available() is True

    @patch("hooty.capture.sys")
    @patch("hooty.capture.Path")
    def test_linux_native(self, mock_path, mock_sys):
        mock_sys.platform = "linux"
        mock_path.return_value.read_text.return_value = "Linux version 6.1.0-generic"
        assert is_capture_available() is False


# --- CaptureResult ---


class TestCaptureResult:
    def test_success(self):
        r = CaptureResult(ok=True, image_path=Path("/tmp/test.png"), message="Active window")
        assert r.ok
        assert r.image_path == Path("/tmp/test.png")

    def test_failure(self):
        r = CaptureResult(ok=False, error="Window not found: foo")
        assert not r.ok
        assert "Window not found" in r.error


# --- is_wsl2 ---


class TestIsWsl2:
    @patch("hooty.capture.sys")
    def test_not_linux(self, mock_sys):
        mock_sys.platform = "win32"
        assert is_wsl2() is False

    @patch("hooty.capture.sys")
    @patch("hooty.capture.Path")
    def test_wsl2(self, mock_path, mock_sys):
        mock_sys.platform = "linux"
        mock_path.return_value.read_text.return_value = (
            "Linux version 5.15.90.1-microsoft-standard-WSL2"
        )
        assert is_wsl2() is True

    @patch("hooty.capture.sys")
    @patch("hooty.capture.Path")
    def test_native_linux(self, mock_path, mock_sys):
        mock_sys.platform = "linux"
        mock_path.return_value.read_text.return_value = "Linux version 6.1.0-generic"
        assert is_wsl2() is False


# --- _format_image_info ---


class TestFormatImageInfo:
    def test_no_resize(self):
        att = Attachment(
            path=Path("/tmp/test.png"), kind="image", display_name="test.png",
            estimated_tokens=2000, orig_width=800, orig_height=600,
            width=800, height=600,
        )
        result = _format_image_info(att)
        assert "800x600" in result
        assert "~2000 tokens" in result
        assert "\u00bb" not in result  # no resize arrow

    def test_with_resize(self):
        att = Attachment(
            path=Path("/tmp/test.png"), kind="image", display_name="test.png",
            estimated_tokens=3000, orig_width=1920, orig_height=1080,
            width=1568, height=882,
        )
        result = _format_image_info(att)
        assert "1920x1080" in result
        assert "1568x882" in result
        assert "\u00bb" in result  # resize arrow present


# --- _strip_app_suffix ---


class TestStripAppSuffix:
    def test_exe(self):
        assert _strip_app_suffix("chrome.exe") == "chrome"

    def test_app(self):
        assert _strip_app_suffix("Chrome.app") == "Chrome"

    def test_no_suffix(self):
        assert _strip_app_suffix("Safari") == "Safari"

    def test_case_insensitive(self):
        assert _strip_app_suffix("Code.EXE") == "Code"


# --- _list_macos_windows ---


def _make_mock_quartz(window_dicts):
    """Create a mock Quartz module that returns the given window dicts."""
    mock_quartz = MagicMock()
    mock_quartz.CGWindowListCopyWindowInfo.return_value = window_dicts
    mock_quartz.NSWorkspace.sharedWorkspace.return_value.frontmostApplication.return_value.processIdentifier.return_value = 1001
    return mock_quartz


_SAMPLE_CG_WINDOWS = [
    {"kCGWindowOwnerName": "Google Chrome", "kCGWindowName": "GitHub",
     "kCGWindowNumber": 100, "kCGWindowOwnerPID": 1001, "kCGWindowLayer": 0,
     "kCGWindowIsOnscreen": True},
    {"kCGWindowOwnerName": "Finder", "kCGWindowName": "Desktop",
     "kCGWindowNumber": 200, "kCGWindowOwnerPID": 1002, "kCGWindowLayer": 0,
     "kCGWindowIsOnscreen": True},
    {"kCGWindowOwnerName": "Dock", "kCGWindowName": "",
     "kCGWindowNumber": 300, "kCGWindowOwnerPID": 1003, "kCGWindowLayer": 20,
     "kCGWindowIsOnscreen": True},
    {"kCGWindowOwnerName": "Safari", "kCGWindowName": "Design Doc",
     "kCGWindowNumber": 400, "kCGWindowOwnerPID": 1004, "kCGWindowLayer": 0,
     "kCGWindowIsOnscreen": True},
    {"kCGWindowOwnerName": "Hidden App", "kCGWindowName": "hidden",
     "kCGWindowNumber": 500, "kCGWindowOwnerPID": 1005, "kCGWindowLayer": 0,
     "kCGWindowIsOnscreen": False},
]


class TestListMacosWindows:
    @patch("hooty.capture._import_quartz")
    def test_filters_onscreen_and_layer(self, mock_import):
        mock_import.return_value = _make_mock_quartz(_SAMPLE_CG_WINDOWS)
        windows = _list_macos_windows()
        assert len(windows) == 3  # Dock (layer 20) and Hidden (not onscreen) excluded
        assert windows[0].owner_name == "Google Chrome"
        assert windows[0].window_id == 100
        assert windows[1].owner_name == "Finder"
        assert windows[2].owner_name == "Safari"

    @patch("hooty.capture._import_quartz")
    def test_empty_result(self, mock_import):
        mock_import.return_value = _make_mock_quartz([])
        assert _list_macos_windows() == []

    @patch("hooty.capture._import_quartz")
    def test_none_result(self, mock_import):
        mock_quartz = MagicMock()
        mock_quartz.CGWindowListCopyWindowInfo.return_value = None
        mock_import.return_value = mock_quartz
        assert _list_macos_windows() == []

    @patch("hooty.capture._import_quartz", return_value=None)
    def test_quartz_not_available(self, _mock_import):
        assert _list_macos_windows() == []


# --- _resolve_macos_target ---


_SAMPLE_WINDOWS = [
    _MacWindow("Google Chrome", "GitHub", 100, 1001, 0),
    _MacWindow("Finder", "Desktop", 200, 1002, 0),
    _MacWindow("Safari", "Design Doc", 400, 1004, 0),
    _MacWindow("Google Chrome", "Gmail", 500, 1001, 0),  # second Chrome window
]


class TestResolveMacosTarget:
    def test_monitor_zero(self):
        args, msg = _resolve_macos_target("0", _SAMPLE_WINDOWS)
        assert args == ["-x", "-D", "1"]
        assert "Monitor #0" in msg

    def test_monitor_primary(self):
        args, msg = _resolve_macos_target("primary", _SAMPLE_WINDOWS)
        assert args == ["-x", "-D", "1"]

    def test_monitor_index(self):
        args, msg = _resolve_macos_target("2", _SAMPLE_WINDOWS)
        assert args == ["-x", "-D", "3"]

    @patch("hooty.capture._get_frontmost_pid", return_value=1001)
    def test_active(self, _mock_pid):
        args, msg = _resolve_macos_target("active", _SAMPLE_WINDOWS)
        assert args == ["-x", "-o", "-l", "100"]  # first Chrome window (z-order)
        assert "Active" in msg

    @patch("hooty.capture._get_frontmost_pid", return_value=9999)
    def test_active_not_found(self, _mock_pid):
        with pytest.raises(ValueError, match="Active window not found"):
            _resolve_macos_target("active", _SAMPLE_WINDOWS)

    def test_app_name_partial(self):
        args, msg = _resolve_macos_target("chrome", _SAMPLE_WINDOWS)
        assert args == ["-x", "-o", "-l", "100"]
        assert "Google Chrome" in msg

    def test_app_name_exe_suffix(self):
        args, msg = _resolve_macos_target("chrome.exe", _SAMPLE_WINDOWS)
        assert args == ["-x", "-o", "-l", "100"]

    def test_app_name_app_suffix(self):
        args, msg = _resolve_macos_target("Safari.app", _SAMPLE_WINDOWS)
        assert args == ["-x", "-o", "-l", "400"]

    def test_title_match(self):
        args, msg = _resolve_macos_target("Design Doc", _SAMPLE_WINDOWS)
        # "design doc" doesn't match any owner_name, falls through to title
        assert args == ["-x", "-o", "-l", "400"]
        assert "Title" in msg

    def test_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            _resolve_macos_target("nonexistent", _SAMPLE_WINDOWS)

    def test_z_order_first_match(self):
        # Two Chrome windows: should pick the first (topmost)
        args, msg = _resolve_macos_target("Chrome", _SAMPLE_WINDOWS)
        assert args == ["-x", "-o", "-l", "100"]  # window_id 100, not 500


# --- _capture_macos ---


class TestCaptureMacos:
    @patch("hooty.capture._import_quartz", return_value=MagicMock())
    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    @patch("hooty.capture._resolve_macos_target", return_value=(["-x", "-o", "-l", "100"], "App: Chrome"))
    @patch("hooty.capture.subprocess.run")
    def test_success(self, mock_run, _mock_resolve, _mock_which, _mock_quartz, tmp_path):
        dest = tmp_path / "capture.png"
        dest.write_bytes(b"\x89PNG fake image data")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = _capture_macos("chrome", dest)
        assert result.ok
        assert result.image_path == dest
        assert result.message == "App: Chrome"

    @patch("hooty.capture.shutil.which", return_value=None)
    def test_screencapture_not_found(self, _mock_which, tmp_path):
        result = _capture_macos("active", tmp_path / "out.png")
        assert not result.ok
        assert "screencapture not found" in result.error

    @patch("hooty.capture._import_quartz", return_value=MagicMock())
    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    @patch("hooty.capture._resolve_macos_target", side_effect=ValueError("Window not found: foo"))
    def test_window_not_found(self, _mock_resolve, _mock_which, _mock_quartz, tmp_path):
        result = _capture_macos("foo", tmp_path / "out.png")
        assert not result.ok
        assert "not found" in result.error

    @patch("hooty.capture._import_quartz", return_value=MagicMock())
    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    @patch("hooty.capture._resolve_macos_target", return_value=(["-x", "-o", "-l", "100"], "App: Chrome"))
    @patch("hooty.capture.subprocess.run")
    def test_permission_denied_empty_file(self, mock_run, _mock_resolve, _mock_which, _mock_quartz, tmp_path):
        dest = tmp_path / "capture.png"
        dest.write_bytes(b"")  # empty file = permission denied
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = _capture_macos("chrome", dest)
        assert not result.ok
        assert "Screen Recording permission" in result.error

    @patch("hooty.capture._import_quartz", return_value=MagicMock())
    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    @patch("hooty.capture._resolve_macos_target", return_value=(["-x", "-o", "-l", "100"], "App: Chrome"))
    @patch("hooty.capture.subprocess.run", side_effect=subprocess.TimeoutExpired("screencapture", 15))
    def test_timeout(self, _mock_run, _mock_resolve, _mock_which, _mock_quartz, tmp_path):
        result = _capture_macos("chrome", tmp_path / "out.png")
        assert not result.ok
        assert "timed out" in result.error

    @patch("hooty.capture._import_quartz", return_value=MagicMock())
    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    @patch("hooty.capture._resolve_macos_target", return_value=(["-x", "-o", "-l", "100"], "App: Chrome"))
    @patch("hooty.capture.subprocess.run")
    def test_nonzero_returncode(self, mock_run, _mock_resolve, _mock_which, _mock_quartz, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="some error")
        result = _capture_macos("chrome", tmp_path / "out.png")
        assert not result.ok
        assert "some error" in result.error

    @patch("hooty.capture._import_quartz", return_value=None)
    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    def test_quartz_not_installed_window_target(self, _mock_which, _mock_quartz, tmp_path):
        result = _capture_macos("chrome", tmp_path / "out.png")
        assert not result.ok
        assert "pyobjc-framework-Quartz" in result.error

    @patch("hooty.capture._import_quartz", return_value=None)
    @patch("hooty.capture.shutil.which", return_value="/usr/sbin/screencapture")
    @patch("hooty.capture.subprocess.run")
    def test_monitor_works_without_quartz(self, mock_run, _mock_which, _mock_quartz, tmp_path):
        dest = tmp_path / "capture.png"
        dest.write_bytes(b"\x89PNG fake image data")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = _capture_macos("0", dest)
        assert result.ok
        assert "Monitor" in result.message

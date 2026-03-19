"""Tests for capture module and /attach capture command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hooty.attachment import Attachment
from hooty.capture import (
    CaptureResult,
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

    @patch("hooty.capture.sys")
    def test_macos(self, mock_sys):
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

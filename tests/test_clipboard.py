"""Tests for hooty.clipboard — clipboard capture logic."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from hooty.clipboard import (
    ClipboardResult,
    Platform,
    capture_clipboard,
    detect_platform,
)


# ---------------------------------------------------------------------------
# detect_platform
# ---------------------------------------------------------------------------

class TestDetectPlatform:
    def test_windows(self):
        with patch("hooty.clipboard.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert detect_platform() == Platform.WINDOWS

    def test_macos(self):
        with patch("hooty.clipboard.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert detect_platform() == Platform.MACOS

    def test_wsl2(self, tmp_path):
        proc_version = tmp_path / "version"
        proc_version.write_text("Linux 5.15.0-1-microsoft-standard-WSL2")
        with (
            patch("hooty.clipboard.sys") as mock_sys,
            patch("hooty.clipboard.Path") as mock_path_cls,
        ):
            mock_sys.platform = "linux"
            mock_path_cls.return_value.read_text.return_value = (
                "Linux 5.15.0-1-microsoft-standard-WSL2"
            )
            assert detect_platform() == Platform.WSL2

    def test_linux(self):
        with (
            patch("hooty.clipboard.sys") as mock_sys,
            patch("hooty.clipboard.Path") as mock_path_cls,
        ):
            mock_sys.platform = "linux"
            mock_path_cls.return_value.read_text.return_value = (
                "Linux 5.15.0-generic"
            )
            assert detect_platform() == Platform.LINUX

    def test_linux_no_proc_version(self):
        with (
            patch("hooty.clipboard.sys") as mock_sys,
            patch("hooty.clipboard.Path") as mock_path_cls,
        ):
            mock_sys.platform = "linux"
            mock_path_cls.return_value.read_text.side_effect = OSError("not found")
            assert detect_platform() == Platform.LINUX

    def test_unknown(self):
        with patch("hooty.clipboard.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            assert detect_platform() == Platform.UNKNOWN


# ---------------------------------------------------------------------------
# capture_clipboard — unsupported platforms
# ---------------------------------------------------------------------------

class TestCaptureUnsupported:
    def test_linux_returns_unsupported(self, tmp_path):
        with patch("hooty.clipboard.detect_platform", return_value=Platform.LINUX):
            result = capture_clipboard(tmp_path)
            assert result.kind == "unsupported"

    def test_unknown_returns_unsupported(self, tmp_path):
        with patch("hooty.clipboard.detect_platform", return_value=Platform.UNKNOWN):
            result = capture_clipboard(tmp_path)
            assert result.kind == "unsupported"


# ---------------------------------------------------------------------------
# Windows/WSL2 backend
# ---------------------------------------------------------------------------

class TestCaptureWindows:
    def test_image_success(self, tmp_path):
        """PowerShell returns OK and image file exists."""
        dest_png = tmp_path / "paste_20260312_120000.png"

        def fake_run(cmd, **kwargs):
            # cmd = [ps_cmd, "-NoProfile", "-Command", script]
            script = cmd[3] if len(cmd) > 3 else ""
            if "GetImage" in script:
                dest_png.write_bytes(b"fakepng")
                return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="NOFILES\n", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.WINDOWS),
            patch("hooty.clipboard.shutil.which", return_value="/usr/bin/powershell"),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "image"
            assert result.image_path == dest_png

    def test_files_success(self, tmp_path):
        """No image, but file drop list returned."""
        dest_png = tmp_path / "paste_dummy.png"

        def fake_run(cmd, **kwargs):
            script = cmd[3] if len(cmd) > 3 else ""
            if "GetImage" in script:
                return subprocess.CompletedProcess(cmd, 0, stdout="NOIMAGE\n", stderr="")
            if "GetFileDropList" in script:
                return subprocess.CompletedProcess(
                    cmd, 0,
                    stdout="C:\\Users\\me\\doc.txt\nC:\\Users\\me\\img.png\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.WINDOWS),
            patch("hooty.clipboard.shutil.which", return_value="/usr/bin/powershell"),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "files"
            assert len(result.file_paths) == 2
            assert result.file_paths[0] == Path("C:\\Users\\me\\doc.txt")

    def test_empty_clipboard(self, tmp_path):
        """No image and no files → empty."""
        dest_png = tmp_path / "paste_dummy.png"

        def fake_run(cmd, **kwargs):
            script = cmd[3] if len(cmd) > 3 else ""
            if "GetImage" in script:
                return subprocess.CompletedProcess(cmd, 0, stdout="NOIMAGE\n", stderr="")
            if "GetFileDropList" in script:
                return subprocess.CompletedProcess(cmd, 0, stdout="NOFILES\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.WINDOWS),
            patch("hooty.clipboard.shutil.which", return_value="/usr/bin/powershell"),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "empty"

    def test_powershell_not_found(self, tmp_path):
        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.WINDOWS),
            patch("hooty.clipboard.shutil.which", return_value=None),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "error"
            assert "not found" in result.error


class TestCaptureWSL2:
    def test_image_with_wslpath(self, tmp_path):
        """WSL2 image capture uses wslpath for path conversion."""
        dest_png = tmp_path / "paste_dummy.png"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "wslpath":
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="W:\\tmp\\paste_dummy.png\n", stderr=""
                )
            if "GetImage" in str(cmd):
                dest_png.write_bytes(b"fakepng")
                return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="NOFILES\n", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.WSL2),
            patch("hooty.clipboard.shutil.which", return_value="/usr/bin/powershell.exe"),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "image"

    def test_files_with_wslpath(self, tmp_path):
        """WSL2 file paths are converted via wslpath -u."""
        dest_png = tmp_path / "paste_dummy.png"

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            if cmd[0] == "wslpath":
                if "-w" in cmd:
                    return subprocess.CompletedProcess(
                        cmd, 0, stdout="W:\\dummy.png\n", stderr=""
                    )
                if "-u" in cmd:
                    return subprocess.CompletedProcess(
                        cmd, 0, stdout=f"/mnt/c/file{call_count}.txt\n", stderr=""
                    )
            if "GetImage" in str(cmd):
                return subprocess.CompletedProcess(cmd, 0, stdout="NOIMAGE\n", stderr="")
            if "GetFileDropList" in str(cmd):
                return subprocess.CompletedProcess(
                    cmd, 0,
                    stdout="C:\\file0.txt\nC:\\file1.txt\n",
                    stderr="",
                )
            call_count += 1
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.WSL2),
            patch("hooty.clipboard.shutil.which", return_value="/usr/bin/powershell.exe"),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "files"
            assert len(result.file_paths) == 2


# ---------------------------------------------------------------------------
# macOS backend
# ---------------------------------------------------------------------------

class TestCaptureMacOS:
    def test_pngpaste_success(self, tmp_path):
        dest_png = tmp_path / "paste_dummy.png"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "pngpaste":
                dest_png.write_bytes(b"fakepng")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="NOIMAGE", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.MACOS),
            patch("hooty.clipboard.shutil.which", return_value="/usr/local/bin/pngpaste"),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "image"
            assert result.image_path == dest_png

    def test_osascript_image_fallback(self, tmp_path):
        dest_png = tmp_path / "paste_dummy.png"

        call_index = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_index
            call_index += 1
            if cmd[0] == "osascript" and "PNGf" in str(cmd):
                dest_png.write_bytes(b"fakepng")
                return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.MACOS),
            patch("hooty.clipboard.shutil.which", return_value=None),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "image"

    def test_file_paths(self, tmp_path):
        dest_png = tmp_path / "paste_dummy.png"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "osascript" and "furl" in str(cmd):
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="/Users/me/doc.txt\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 1, stdout="NOIMAGE", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.MACOS),
            patch("hooty.clipboard.shutil.which", return_value=None),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "files"
            assert result.file_paths[0] == Path("/Users/me/doc.txt")

    def test_empty(self, tmp_path):
        dest_png = tmp_path / "paste_dummy.png"

        def fake_run(cmd, **kwargs):
            if "furl" in str(cmd):
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")
            return subprocess.CompletedProcess(cmd, 1, stdout="NOIMAGE", stderr="")

        with (
            patch("hooty.clipboard.detect_platform", return_value=Platform.MACOS),
            patch("hooty.clipboard.shutil.which", return_value=None),
            patch("hooty.clipboard.subprocess.run", side_effect=fake_run),
            patch("hooty.clipboard._make_dest_path", return_value=dest_png),
        ):
            result = capture_clipboard(tmp_path)
            assert result.kind == "empty"


# ---------------------------------------------------------------------------
# _is_duplicate_image
# ---------------------------------------------------------------------------

def _make_test_png(path, color=(255, 0, 0)):
    """Create a small real PNG file for testing."""
    from PIL import Image as PILImage

    img = PILImage.new("RGB", (4, 4), color)
    img.save(path, format="PNG")
    img.close()


class TestIsDuplicateImage:
    def test_duplicate_detected(self, tmp_path):
        from hooty.commands.attach import _is_duplicate_image

        new_file = tmp_path / "new.png"
        existing_file = tmp_path / "existing.png"
        _make_test_png(new_file, color=(255, 0, 0))
        _make_test_png(existing_file, color=(255, 0, 0))

        item = MagicMock()
        item.kind = "image"
        item.path = existing_file
        stack = MagicMock()
        stack.items.return_value = [item]

        assert _is_duplicate_image(stack, new_file) is True

    def test_no_duplicate(self, tmp_path):
        from hooty.commands.attach import _is_duplicate_image

        new_file = tmp_path / "new.png"
        existing_file = tmp_path / "existing.png"
        _make_test_png(new_file, color=(255, 0, 0))
        _make_test_png(existing_file, color=(0, 0, 255))

        item = MagicMock()
        item.kind = "image"
        item.path = existing_file
        stack = MagicMock()
        stack.items.return_value = [item]

        assert _is_duplicate_image(stack, new_file) is False

    def test_empty_stack(self, tmp_path):
        from hooty.commands.attach import _is_duplicate_image

        new_file = tmp_path / "new.png"
        _make_test_png(new_file)
        stack = MagicMock()
        stack.items.return_value = []

        assert _is_duplicate_image(stack, new_file) is False


# ---------------------------------------------------------------------------
# /attach paste routing
# ---------------------------------------------------------------------------

class TestAttachPasteRouting:
    def test_paste_routes_image(self):
        """_attach_paste calls _add_file for image result."""
        from hooty.commands.attach import _attach_paste

        mock_result = ClipboardResult(kind="image", image_path=Path("/tmp/paste.png"))

        ctx = MagicMock()
        ctx.config.session_dir = Path("/tmp/session")
        stack = MagicMock()

        with patch("hooty.clipboard.capture_clipboard", return_value=mock_result):
            with patch("hooty.commands.attach._is_duplicate_image", return_value=False):
                with patch("hooty.commands.attach._add_file") as mock_add:
                    _attach_paste(ctx, stack)
                    mock_add.assert_called_once_with(ctx, stack, "/tmp/paste.png")

    def test_paste_skips_duplicate_image(self, tmp_path):
        """_attach_paste skips duplicate image and shows message."""
        from hooty.commands.attach import _attach_paste

        dup_file = tmp_path / "paste.png"
        dup_file.write_bytes(b"fakepng")
        mock_result = ClipboardResult(kind="image", image_path=dup_file)

        ctx = MagicMock()
        ctx.config.session_dir = Path("/tmp/session")
        stack = MagicMock()

        with patch("hooty.clipboard.capture_clipboard", return_value=mock_result):
            with patch("hooty.commands.attach._is_duplicate_image", return_value=True):
                with patch("hooty.commands.attach._add_file") as mock_add:
                    _attach_paste(ctx, stack)
                    mock_add.assert_not_called()
                    ctx.console.print.assert_any_call(
                        "  [dim]Same image already attached (skipped).[/dim]"
                    )
                    assert not dup_file.exists()  # cleaned up

    def test_paste_routes_files(self):
        """_attach_paste calls _add_file for each file in clipboard."""
        from hooty.commands.attach import _attach_paste

        mock_result = ClipboardResult(
            kind="files",
            file_paths=[Path("/tmp/a.txt"), Path("/tmp/b.txt")],
        )

        ctx = MagicMock()
        ctx.config.session_dir = Path("/tmp/session")
        stack = MagicMock()

        with patch("hooty.clipboard.capture_clipboard", return_value=mock_result):
            with patch("hooty.commands.attach._add_file") as mock_add:
                _attach_paste(ctx, stack)
                assert mock_add.call_count == 2

    def test_paste_routes_empty(self):
        """_attach_paste prints message for empty clipboard."""
        from hooty.commands.attach import _attach_paste

        mock_result = ClipboardResult(kind="empty")
        ctx = MagicMock()
        ctx.config.session_dir = Path("/tmp/session")

        with patch("hooty.clipboard.capture_clipboard", return_value=mock_result):
            _attach_paste(ctx, MagicMock())
            ctx.console.print.assert_any_call(
                "  [dim]No image or files found in clipboard.[/dim]"
            )

    def test_paste_routes_unsupported(self):
        """_attach_paste prints unsupported message for Linux."""
        from hooty.commands.attach import _attach_paste

        mock_result = ClipboardResult(kind="unsupported")
        ctx = MagicMock()
        ctx.config.session_dir = Path("/tmp/session")

        with patch("hooty.clipboard.capture_clipboard", return_value=mock_result):
            _attach_paste(ctx, MagicMock())
            # Check that console.print was called with unsupported message
            calls = [str(c) for c in ctx.console.print.call_args_list]
            assert any("not supported" in c for c in calls)

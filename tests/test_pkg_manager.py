"""Tests for pkg_manager module."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from hooty.pkg_manager import (
    _binary_filename,
    _match_binary,
    download_pkg,
    ensure_pkg,
    find_pkg,
    missing_packages,
    platform_tag,
)


class TestPlatformTag:
    """Test platform_tag() returns correct OS/arch tags."""

    def test_linux_x86_64(self):
        with patch("hooty.pkg_manager.platform.machine", return_value="x86_64"), \
             patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert platform_tag() == "x86_64-linux"

    def test_windows_amd64(self):
        with patch("hooty.pkg_manager.platform.machine", return_value="AMD64"), \
             patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert platform_tag() == "x86_64-windows"

    def test_darwin_arm64(self):
        with patch("hooty.pkg_manager.platform.machine", return_value="arm64"), \
             patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert platform_tag() == "aarch64-darwin"

    def test_darwin_x86_64(self):
        with patch("hooty.pkg_manager.platform.machine", return_value="x86_64"), \
             patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert platform_tag() == "x86_64-darwin"


class TestBinaryFilename:
    """Test _binary_filename appends .exe on Windows."""

    def test_non_windows(self):
        with patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert _binary_filename("rg") == "rg"

    def test_windows(self):
        with patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert _binary_filename("rg") == "rg.exe"


class TestFindPkg:
    """Test find_pkg local cache and PATH lookup."""

    def test_finds_in_local_cache(self, tmp_path):
        tag = "x86_64-linux"
        pkg_dir = tmp_path / "pkg" / tag
        pkg_dir.mkdir(parents=True)
        binary = pkg_dir / "rg"
        binary.write_text("binary")

        with patch("hooty.pkg_manager._hooty_dir", return_value=tmp_path), \
             patch("hooty.pkg_manager.platform_tag", return_value=tag), \
             patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = find_pkg("rg")
        assert result == str(binary)

    def test_finds_on_path(self, tmp_path):
        with patch("hooty.pkg_manager._hooty_dir", return_value=tmp_path), \
             patch("hooty.pkg_manager.platform_tag", return_value="x86_64-linux"), \
             patch("hooty.pkg_manager.sys") as mock_sys, \
             patch("shutil.which", return_value="/usr/bin/rg"):
            mock_sys.platform = "linux"
            result = find_pkg("rg")
        assert result == "/usr/bin/rg"

    def test_returns_none_when_not_found(self, tmp_path):
        with patch("hooty.pkg_manager._hooty_dir", return_value=tmp_path), \
             patch("hooty.pkg_manager.platform_tag", return_value="x86_64-linux"), \
             patch("hooty.pkg_manager.sys") as mock_sys, \
             patch("shutil.which", return_value=None):
            mock_sys.platform = "linux"
            result = find_pkg("rg")
        assert result is None

    def test_local_cache_has_priority_over_path(self, tmp_path):
        tag = "x86_64-linux"
        pkg_dir = tmp_path / "pkg" / tag
        pkg_dir.mkdir(parents=True)
        binary = pkg_dir / "rg"
        binary.write_text("binary")

        with patch("hooty.pkg_manager._hooty_dir", return_value=tmp_path), \
             patch("hooty.pkg_manager.platform_tag", return_value=tag), \
             patch("hooty.pkg_manager.sys") as mock_sys, \
             patch("shutil.which", return_value="/usr/bin/rg"):
            mock_sys.platform = "linux"
            result = find_pkg("rg")
        # Local cache takes precedence
        assert result == str(binary)


class TestEnsurePkg:
    """Test ensure_pkg find-or-download logic."""

    def test_returns_existing(self, tmp_path):
        with patch("hooty.pkg_manager.find_pkg", return_value="/usr/bin/rg"):
            assert ensure_pkg("rg") == "/usr/bin/rg"

    def test_downloads_when_missing(self):
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("hooty.pkg_manager.download_pkg", return_value="/home/.hooty/pkg/x86_64-linux/rg") as mock_dl:
            result = ensure_pkg("rg")
        assert result == "/home/.hooty/pkg/x86_64-linux/rg"
        mock_dl.assert_called_once_with("rg")


class TestMissingPackages:
    """Test missing_packages() detection."""

    def test_returns_empty_when_all_found(self):
        with patch("hooty.pkg_manager.find_pkg", return_value="/usr/bin/rg"), \
             patch("hooty.pkg_manager.platform_tag", return_value="x86_64-linux"):
            assert missing_packages() == []

    def test_returns_missing_when_not_found(self):
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("hooty.pkg_manager.platform_tag", return_value="x86_64-linux"):
            result = missing_packages()
        assert len(result) >= 1
        names = [name for name, _ in result]
        assert "rg" in names

    def test_includes_display_name(self):
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("hooty.pkg_manager.platform_tag", return_value="x86_64-linux"):
            result = missing_packages()
        displays = [display for _, display in result]
        assert any("ripgrep" in d for d in displays)

    def test_skips_unsupported_platform(self):
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("hooty.pkg_manager.platform_tag", return_value="sparc-solaris"):
            assert missing_packages() == []


class TestMatchBinary:
    """Test _match_binary correctly identifies the real binary."""

    def test_exact_match(self):
        assert _match_binary("rg", "rg") is True

    def test_in_subdirectory(self):
        assert _match_binary("ripgrep-14.0.0-x86_64-unknown-linux-musl/rg", "rg") is True

    def test_rejects_completion_script(self):
        assert _match_binary("ripgrep-14.0.0/complete/_rg", "rg") is False

    def test_rejects_partial_suffix(self):
        assert _match_binary("doc/CHANGELOG", "LOG") is False

    def test_exe_on_windows(self):
        assert _match_binary("ripgrep-14.0.0/rg.exe", "rg.exe") is True

    def test_rejects_similar_name(self):
        assert _match_binary("ripgrep-14.0.0/rg.1", "rg") is False


class TestDownloadPkg:
    """Test download_pkg with mocked HTTP."""

    def test_unknown_package_returns_none(self):
        assert download_pkg("nonexistent") is None

    def test_unsupported_platform_returns_none(self):
        with patch("hooty.pkg_manager.platform_tag", return_value="sparc-solaris"):
            assert download_pkg("rg") is None

    def test_download_and_extract_zip(self, tmp_path):
        """Simulate downloading a .zip archive for Windows."""
        import io
        import zipfile

        # Create a fake zip containing rg.exe
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ripgrep-14.0.0-x86_64-pc-windows-msvc/rg.exe", b"fake-binary")
        zip_bytes = buf.getvalue()

        # Mock GitHub API
        release_json = json.dumps({
            "assets": [{
                "name": "ripgrep-14.0.0-x86_64-pc-windows-msvc.zip",
                "browser_download_url": "https://example.com/rg.zip",
            }]
        }).encode()

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            resp = MagicMock()
            if call_count[0] == 0:
                resp.read.return_value = release_json
            else:
                resp.read.return_value = zip_bytes
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            call_count[0] += 1
            return resp

        with patch("hooty.pkg_manager.urlopen", side_effect=mock_urlopen), \
             patch("hooty.pkg_manager._hooty_dir", return_value=tmp_path), \
             patch("hooty.pkg_manager.platform_tag", return_value="x86_64-windows"), \
             patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "win32"
            result = download_pkg("rg")

        assert result is not None
        assert Path(result).name == "rg.exe"
        assert Path(result).exists()

    def test_download_and_extract_tar(self, tmp_path):
        """Simulate downloading a .tar.gz archive for Linux."""
        import io
        import tarfile

        # Create a fake tar.gz containing rg AND a decoy complete/_rg
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            # Decoy: completion script (should be skipped)
            decoy = b"#!/bin/zsh\n#compdef rg\n"
            decoy_info = tarfile.TarInfo(name="ripgrep-14.0.0-x86_64-unknown-linux-musl/complete/_rg")
            decoy_info.size = len(decoy)
            tf.addfile(decoy_info, io.BytesIO(decoy))
            # Real binary
            data = b"fake-binary"
            info = tarfile.TarInfo(name="ripgrep-14.0.0-x86_64-unknown-linux-musl/rg")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        tar_bytes = buf.getvalue()

        release_json = json.dumps({
            "assets": [{
                "name": "ripgrep-14.0.0-x86_64-unknown-linux-musl.tar.gz",
                "browser_download_url": "https://example.com/rg.tar.gz",
            }]
        }).encode()

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            resp = MagicMock()
            if call_count[0] == 0:
                resp.read.return_value = release_json
            else:
                resp.read.return_value = tar_bytes
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            call_count[0] += 1
            return resp

        with patch("hooty.pkg_manager.urlopen", side_effect=mock_urlopen), \
             patch("hooty.pkg_manager._hooty_dir", return_value=tmp_path), \
             patch("hooty.pkg_manager.platform_tag", return_value="x86_64-linux"), \
             patch("hooty.pkg_manager.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = download_pkg("rg")

        assert result is not None
        assert Path(result).name == "rg"
        assert Path(result).exists()
        # Check executable permission on Unix
        if sys.platform != "win32":
            import stat
            mode = Path(result).stat().st_mode
            assert mode & stat.S_IXUSR

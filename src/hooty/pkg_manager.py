"""Generic binary package manager for Hooty.

Downloads pre-built binaries (rg, fd, bat, etc.) from GitHub Releases
and caches them under ``~/.hooty/pkg/<platform_tag>/``.
"""

from __future__ import annotations

import io
import json
import logging
import platform
import shutil
import stat
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("hooty")

_PKG_DIR_NAME = "pkg"


def _hooty_dir() -> Path:
    return Path.home() / ".hooty"


def platform_tag() -> str:
    """Return ``{arch}-{os}`` tag for the current platform.

    Examples: ``x86_64-windows``, ``x86_64-linux``, ``aarch64-darwin``.
    """
    machine = platform.machine().lower()
    # Normalize common aliases
    arch_map = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    arch = arch_map.get(machine, machine)

    if sys.platform == "win32":
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "darwin"
    else:
        os_name = "linux"

    return f"{arch}-{os_name}"


@dataclass
class PkgInfo:
    """Registry entry for a downloadable binary package."""

    repo: str  # GitHub owner/repo
    display_name: str = ""  # Human-readable name shown in UI
    # Map platform_tag -> (rust-target-triple-fragment, archive-extension)
    targets: dict[str, tuple[str, str]] = field(default_factory=dict)
    binary_name: str = ""  # Base name of the binary inside the archive


_REGISTRY: dict[str, PkgInfo] = {
    "rg": PkgInfo(
        repo="BurntSushi/ripgrep",
        display_name="ripgrep (rg)",
        targets={
            "x86_64-windows": ("x86_64-pc-windows-msvc", ".zip"),
            "x86_64-linux": ("x86_64-unknown-linux-musl", ".tar.gz"),
            "x86_64-darwin": ("x86_64-apple-darwin", ".tar.gz"),
            "aarch64-darwin": ("aarch64-apple-darwin", ".tar.gz"),
            "aarch64-linux": ("aarch64-unknown-linux-gnu", ".tar.gz"),
        },
        binary_name="rg",
    ),
}


def missing_packages() -> list[tuple[str, str]]:
    """Return list of ``(name, display_name)`` for packages not yet available."""
    missing: list[tuple[str, str]] = []
    tag = platform_tag()
    for name, info in _REGISTRY.items():
        if tag not in info.targets:
            continue  # not supported on this platform
        if find_pkg(name) is None:
            missing.append((name, info.display_name or name))
    return missing


def pkg_dir() -> str | None:
    """Return the managed package directory path, or None if it doesn't exist."""
    d = _hooty_dir() / _PKG_DIR_NAME / platform_tag()
    return str(d) if d.is_dir() else None


def _pkg_dir(tag: str | None = None) -> Path:
    """Return the package cache directory for the given platform tag."""
    return _hooty_dir() / _PKG_DIR_NAME / (tag or platform_tag())


def _binary_filename(name: str) -> str:
    """Return the binary file name, appending .exe on Windows."""
    if sys.platform == "win32":
        return f"{name}.exe"
    return name


def find_pkg(name: str) -> str | None:
    """Find a package binary without downloading.

    1. ``~/.hooty/pkg/{platform_tag()}/{name}[.exe]``
    2. ``shutil.which(name)``
    3. ``None``
    """
    # Check local cache first
    local = _pkg_dir() / _binary_filename(name)
    if local.is_file():
        return str(local)

    # Check PATH
    which_result = shutil.which(name)
    if which_result:
        return which_result

    return None


def ensure_pkg(name: str) -> str | None:
    """Find or download a package binary.

    Returns the path to the binary, or ``None`` on failure.
    """
    found = find_pkg(name)
    if found:
        return found
    return download_pkg(name)


def download_pkg(name: str) -> str | None:
    """Download a package from GitHub Releases.

    Returns the path to the installed binary, or ``None`` on failure.
    """
    info = _REGISTRY.get(name)
    if info is None:
        logger.debug("pkg_manager: unknown package %r", name)
        return None

    tag = platform_tag()
    target_info = info.targets.get(tag)
    if target_info is None:
        logger.debug("pkg_manager: no target for %r on %s", name, tag)
        return None

    triple_fragment, ext = target_info

    try:
        # Get latest release
        api_url = f"https://api.github.com/repos/{info.repo}/releases/latest"
        req = Request(api_url, headers={"Accept": "application/vnd.github+json"})
        with urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read())

        # Find matching asset
        asset_url: str | None = None
        for asset in release.get("assets", []):
            aname: str = asset["name"]
            if triple_fragment in aname and aname.endswith(ext):
                asset_url = asset["browser_download_url"]
                break

        if not asset_url:
            logger.debug("pkg_manager: no matching asset for %r (%s, %s)", name, triple_fragment, ext)
            return None

        # Download
        logger.debug("pkg_manager: downloading %s", asset_url)
        req = Request(asset_url)
        with urlopen(req, timeout=120) as resp:
            archive_bytes = resp.read()

        # Extract binary
        binary_name = _binary_filename(info.binary_name or name)
        dest_dir = _pkg_dir(tag)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / binary_name

        if ext == ".zip":
            _extract_from_zip(archive_bytes, binary_name, dest_path)
        elif ext == ".tar.gz":
            _extract_from_tar(archive_bytes, binary_name, dest_path)
        else:
            logger.debug("pkg_manager: unsupported archive format %s", ext)
            return None

        # Set executable permission on Unix
        if sys.platform != "win32":
            dest_path.chmod(dest_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        logger.debug("pkg_manager: installed %s -> %s", name, dest_path)
        return str(dest_path)

    except (URLError, OSError, json.JSONDecodeError, KeyError) as exc:
        logger.debug("pkg_manager: download failed for %r: %s", name, exc)
        return None


def _match_binary(entry_name: str, binary_name: str) -> bool:
    """Check if an archive entry is the target binary (not a similarly-named file).

    Matches ``rg``, ``dir/rg``, ``dir/rg.exe`` but NOT ``complete/_rg``.
    Uses the POSIX basename of the entry to avoid false positives.
    """
    basename = entry_name.rsplit("/", 1)[-1]
    return basename == binary_name


def _extract_from_zip(data: bytes, binary_name: str, dest_path: Path) -> None:
    """Extract a binary from a zip archive."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for entry in zf.namelist():
            if _match_binary(entry, binary_name) and not entry.endswith("/"):
                with zf.open(entry) as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())
                return
        raise FileNotFoundError(f"{binary_name} not found in zip archive")


def _extract_from_tar(data: bytes, binary_name: str, dest_path: Path) -> None:
    """Extract a binary from a tar.gz archive."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for member in tf.getmembers():
            if _match_binary(member.name, binary_name) and member.isfile():
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                with open(dest_path, "wb") as dst:
                    dst.write(extracted.read())
                return
        raise FileNotFoundError(f"{binary_name} not found in tar archive")

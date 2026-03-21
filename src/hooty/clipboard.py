"""Clipboard capture for /attach paste — images and file paths from system clipboard."""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import strftime


class Platform(Enum):
    WINDOWS = "windows"
    WSL2 = "wsl2"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"


@dataclass
class ClipboardResult:
    """Result of a clipboard capture attempt."""

    kind: str  # "image" | "files" | "empty" | "unsupported" | "error"
    image_path: Path | None = None
    file_paths: list[Path] = field(default_factory=list)
    error: str | None = None


def detect_platform() -> Platform:
    """Detect the current platform for clipboard access."""
    if sys.platform == "win32":
        return Platform.WINDOWS
    if sys.platform == "darwin":
        return Platform.MACOS
    if sys.platform == "linux":
        try:
            version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
            if "microsoft" in version.lower():
                return Platform.WSL2
        except OSError:
            pass
        return Platform.LINUX
    return Platform.UNKNOWN


def capture_clipboard(dest_dir: Path) -> ClipboardResult:
    """Capture clipboard content (image or file paths).

    Args:
        dest_dir: Directory to save captured images into.

    Returns:
        ClipboardResult with the capture outcome.
    """
    platform = detect_platform()

    if platform in (Platform.LINUX, Platform.UNKNOWN):
        return ClipboardResult(kind="unsupported")

    try:
        if platform == Platform.WINDOWS:
            return _capture_windows(dest_dir, ps_cmd="powershell")
        elif platform == Platform.WSL2:
            return _capture_windows(dest_dir, ps_cmd="powershell.exe")
        elif platform == Platform.MACOS:
            return _capture_macos(dest_dir)
    except Exception as e:
        return ClipboardResult(kind="error", error=str(e))

    return ClipboardResult(kind="unsupported")  # pragma: no cover


def _make_dest_path(dest_dir: Path) -> Path:
    """Generate a timestamped PNG filename in dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / f"paste_{strftime('%Y%m%d_%H%M%S')}.png"


def _capture_windows(dest_dir: Path, *, ps_cmd: str) -> ClipboardResult:
    """Capture clipboard via PowerShell (Windows / WSL2)."""
    if not shutil.which(ps_cmd):
        return ClipboardResult(kind="error", error=f"{ps_cmd} not found")

    # --- Try image first ---
    dest_path = _make_dest_path(dest_dir)

    if ps_cmd == "powershell.exe":
        # WSL2: convert dest to Windows path
        try:
            win_path = subprocess.run(
                ["wslpath", "-w", str(dest_path)],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ClipboardResult(kind="error", error="wslpath conversion failed")
    else:
        win_path = str(dest_path)

    ps_image_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$img = [System.Windows.Forms.Clipboard]::GetImage(); "
        "if ($img -ne $null) { "
        f"  $img.Save('{win_path}', [System.Drawing.Imaging.ImageFormat]::Png); "
        "  Write-Output 'OK' "
        "} else { "
        "  Write-Output 'NOIMAGE' "
        "}"
    )

    result = subprocess.run(
        [ps_cmd, "-NoProfile", "-Command", ps_image_script],
        capture_output=True, text=True, timeout=10,
    )
    stdout = result.stdout.strip()

    if stdout == "OK" and dest_path.exists():
        return ClipboardResult(kind="image", image_path=dest_path)

    # --- Try file drop list ---
    ps_files_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$files = [System.Windows.Forms.Clipboard]::GetFileDropList(); "
        "if ($files.Count -gt 0) { "
        "  foreach ($f in $files) { Write-Output $f } "
        "} else { "
        "  Write-Output 'NOFILES' "
        "}"
    )

    result = subprocess.run(
        [ps_cmd, "-NoProfile", "-Command", ps_files_script],
        capture_output=True, text=True, timeout=10,
    )
    stdout = result.stdout.strip()

    if stdout and stdout != "NOFILES":
        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        paths: list[Path] = []
        for line in lines:
            if ps_cmd == "powershell.exe":
                # WSL2: convert Windows path to Unix
                try:
                    unix = subprocess.run(
                        ["wslpath", "-u", line],
                        capture_output=True, text=True, timeout=5,
                    ).stdout.strip()
                    paths.append(Path(unix))
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    paths.append(Path(line))
            else:
                paths.append(Path(line))
        if paths:
            return ClipboardResult(kind="files", file_paths=paths)

    return ClipboardResult(kind="empty")


def write_clipboard(text: str) -> tuple[bool, str]:
    """Write text to system clipboard. Returns (success, error_message)."""
    platform = detect_platform()

    if platform in (Platform.WINDOWS, Platform.WSL2):
        return _write_clipboard_powershell(text, platform)

    if platform == Platform.MACOS:
        cmd = ["pbcopy"]
    elif platform == Platform.LINUX:
        if shutil.which("xclip"):
            cmd = ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            cmd = ["xsel", "--clipboard", "--input"]
        else:
            return False, "No clipboard tool found (install xclip or xsel)"
    else:
        return False, "Unsupported platform for clipboard write"

    try:
        result = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"Command failed with exit code {result.returncode}"
            return False, err
        return True, ""
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "Clipboard write timed out"
    except Exception as e:
        return False, str(e)


def _write_clipboard_powershell(text: str, platform: Platform) -> tuple[bool, str]:
    """Write text to clipboard via PowerShell.

    Pipes base64-encoded text through stdin (pure ASCII) to avoid
    encoding issues with multi-byte characters on Windows.
    """
    ps_cmd = "powershell" if platform == Platform.WINDOWS else "powershell.exe"
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    # Pipe base64 (ASCII-safe) via stdin; decode to UTF-8 in PowerShell.
    script = (
        "$b64 = @($input) -join '';"
        "$bytes = [System.Convert]::FromBase64String($b64);"
        "$text = [System.Text.Encoding]::UTF8.GetString($bytes);"
        "Set-Clipboard -Value $text"
    )
    try:
        result = subprocess.run(
            [ps_cmd, "-NoProfile", "-Command", script],
            input=b64,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"Command failed with exit code {result.returncode}"
            return False, err
        return True, ""
    except FileNotFoundError:
        return False, f"Command not found: {ps_cmd}"
    except subprocess.TimeoutExpired:
        return False, "Clipboard write timed out"
    except Exception as e:
        return False, str(e)


def _capture_macos(dest_dir: Path) -> ClipboardResult:
    """Capture clipboard on macOS via pngpaste / osascript."""
    dest_path = _make_dest_path(dest_dir)

    # --- Try image: pngpaste first ---
    if shutil.which("pngpaste"):
        result = subprocess.run(
            ["pngpaste", str(dest_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and dest_path.exists():
            return ClipboardResult(kind="image", image_path=dest_path)

    # --- Try image: osascript fallback ---
    osa_script = (
        'try\n'
        '  set imgData to the clipboard as «class PNGf»\n'
        f'  set fp to open for access POSIX file "{dest_path}" with write permission\n'
        '  write imgData to fp\n'
        '  close access fp\n'
        '  return "OK"\n'
        'on error\n'
        '  return "NOIMAGE"\n'
        'end try'
    )
    result = subprocess.run(
        ["osascript", "-e", osa_script],
        capture_output=True, text=True, timeout=10,
    )
    if result.stdout.strip() == "OK" and dest_path.exists():
        return ClipboardResult(kind="image", image_path=dest_path)

    # --- Try file paths ---
    result = subprocess.run(
        ["osascript", "-e", 'POSIX path of (the clipboard as «class furl»)'],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        paths = [Path(ln) for ln in lines]
        if paths:
            return ClipboardResult(kind="files", file_paths=paths)

    return ClipboardResult(kind="empty")

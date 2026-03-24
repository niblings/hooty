"""Screen capture for /attach capture — Windows/WSL2 (PowerShell) and macOS (screencapture)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaptureResult:
    """Result of a screen capture attempt."""

    ok: bool
    image_path: Path | None = None
    error: str | None = None
    message: str | None = None  # success info (e.g. "Window (Title: Design Doc)")


def is_capture_available() -> bool:
    """Check if screen capture is supported on this platform."""
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        return shutil.which("screencapture") is not None
    if sys.platform == "linux":
        return _is_wsl2()
    return False


def _is_wsl2() -> bool:
    """Check if running on WSL2."""
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        return "microsoft" in version.lower()
    except OSError:
        return False


def is_wsl2() -> bool:
    """Check if running on WSL2 (public API)."""
    if sys.platform != "linux":
        return False
    return _is_wsl2()


def _get_ps_cmd() -> str:
    """Return the PowerShell command for the current platform."""
    if sys.platform == "win32":
        return "powershell"
    return "powershell.exe"  # WSL2


def _to_win_path(path: Path) -> str:
    """Convert a path to Windows format (for WSL2)."""
    if sys.platform == "win32":
        return str(path)
    try:
        result = subprocess.run(
            ["wslpath", "-w", str(path)],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return str(path)


def _build_ps_script(target: str, win_dest_path: str) -> str:
    """Build PowerShell script for screen capture.

    The script captures the specified target and saves directly to a PNG file.
    """
    # Escape single quotes in paths/target for PowerShell
    safe_dest = win_dest_path.replace("'", "''")
    safe_target = target.replace("'", "''")

    return f"""\
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$code = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win32Capture {{
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {{ public int Left, Top, Right, Bottom; }}
}}
'@

if (-not ([System.Management.Automation.PSTypeName]'Win32Capture').Type) {{
    Add-Type -TypeDefinition $code
}}

$target = '{safe_target}'
$destPath = '{safe_dest}'
$rect = New-Object Win32Capture+RECT
$handle = [IntPtr]::Zero
$isMonitor = $false
$msg = ''

# --- Target detection ---
if ($target -match '^\\d+$' -or $target -eq 'primary') {{
    $isMonitor = $true
    $index = if ($target -eq 'primary') {{ 0 }} else {{ [int]$target }}
    $screens = [System.Windows.Forms.Screen]::AllScreens
    if ($index -ge $screens.Count) {{
        Write-Output "ERROR:Monitor #$index not found (available: 0-$($screens.Count - 1))"
        exit 0
    }}
    $s = $screens[$index]
    $left = $s.Bounds.X; $top = $s.Bounds.Y
    $width = $s.Bounds.Width; $height = $s.Bounds.Height
    $msg = "Monitor #$index"
}} else {{
    $procs = Get-Process | Where-Object {{ $_.MainWindowHandle -ne 0 }}

    if ($target -eq 'active') {{
        $handle = [Win32Capture]::GetForegroundWindow()
        $msg = 'Active window'
    }} elseif ($target -like '*.exe') {{
        $exeName = $target -replace '\\.exe$', ''
        $p = $procs | Where-Object {{ $_.ProcessName -eq $exeName }} | Select-Object -First 1
        if ($p) {{
            $handle = $p.MainWindowHandle
            $msg = "Process: $target"
        }}
    }} else {{
        # Try class name first
        $targetHwnd = $null
        foreach ($proc in $procs) {{
            $h = $proc.MainWindowHandle
            $sb = New-Object System.Text.StringBuilder 256
            [Win32Capture]::GetClassName($h, $sb, $sb.Capacity) | Out-Null
            if ($sb.ToString() -eq $target) {{
                $targetHwnd = $h
                break
            }}
        }}

        if ($targetHwnd) {{
            $handle = $targetHwnd
            $msg = "Class: $target"
        }} else {{
            # Title partial match (escape wildcard chars in target)
            $esc = $target -replace '([\\*\\?\\[\\]])', '`$1'
            $p = $procs | Where-Object {{ $_.MainWindowTitle -like "*$esc*" }} | Select-Object -First 1
            if ($p) {{
                $handle = $p.MainWindowHandle
                $msg = "Title: $target"
            }}
        }}
    }}

    if ($handle -eq [IntPtr]::Zero) {{
        Write-Output "ERROR:Window or Process not found: $target"
        exit 0
    }}

    [Win32Capture]::GetWindowRect($handle, [ref]$rect) | Out-Null
    $left = $rect.Left; $top = $rect.Top
    $width = $rect.Right - $rect.Left; $height = $rect.Bottom - $rect.Top
}}

# --- Capture ---
if ($width -gt 0 -and $height -gt 0) {{
    $bmp = New-Object System.Drawing.Bitmap($width, $height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($left, $top, 0, 0, $bmp.Size)
    $bmp.Save($destPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "OK:$msg"
}} else {{
    Write-Output "ERROR:Captured area has zero size"
}}
"""


def capture_screen(target: str, dest_path: Path) -> CaptureResult:
    """Capture a screen region and save as PNG.

    Args:
        target: Capture target (active, monitor number, process name, or title).
        dest_path: Where to save the PNG file.

    Returns:
        CaptureResult with outcome.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        return _capture_macos(target, dest_path)
    return _capture_windows(target, dest_path)


# ---------------------------------------------------------------------------
# Windows / WSL2 backend
# ---------------------------------------------------------------------------


def _capture_windows(target: str, dest_path: Path) -> CaptureResult:
    """Capture via PowerShell on Windows / WSL2."""
    ps_cmd = _get_ps_cmd()
    if not shutil.which(ps_cmd):
        return CaptureResult(ok=False, error=f"{ps_cmd} not found")

    win_path = _to_win_path(dest_path)
    script = _build_ps_script(target, win_path)

    try:
        result = subprocess.run(
            [ps_cmd, "-NoProfile", "-Command", script],
            capture_output=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return CaptureResult(ok=False, error="PowerShell timed out")
    except Exception as e:
        return CaptureResult(ok=False, error=str(e))

    stdout = result.stdout.strip()

    if stdout.startswith("OK:"):
        msg = stdout[3:]
        if dest_path.exists():
            return CaptureResult(ok=True, image_path=dest_path, message=msg)
        return CaptureResult(ok=False, error="Capture succeeded but file not found")

    if stdout.startswith("ERROR:"):
        return CaptureResult(ok=False, error=stdout[6:])

    # Unexpected output
    stderr = result.stderr.strip()
    return CaptureResult(
        ok=False,
        error=stderr or stdout or "Unknown capture error",
    )


# ---------------------------------------------------------------------------
# macOS backend
# ---------------------------------------------------------------------------


@dataclass
class _MacWindow:
    """On-screen window info from CGWindowListCopyWindowInfo."""

    owner_name: str   # kCGWindowOwnerName (e.g. "Google Chrome")
    window_name: str  # kCGWindowName (e.g. tab/document title)
    window_id: int    # kCGWindowNumber — passed to screencapture -l
    owner_pid: int    # kCGWindowOwnerPID
    layer: int        # kCGWindowLayer (0 = normal window)


def _import_quartz():
    """Import Quartz framework (macOS only, requires pyobjc-framework-Quartz)."""
    try:
        import Quartz  # type: ignore[import-not-found]
        return Quartz
    except ImportError:
        return None


def _list_macos_windows() -> list[_MacWindow]:
    """List on-screen windows (z-order: front-to-back, layer 0 only).

    Uses CGWindowListCopyWindowInfo with kCGWindowListOptionAll (= 0)
    because kCGWindowListOptionOnScreenOnly returns empty on macOS 15+.
    Results are filtered to on-screen, layer-0 windows in Python.
    """
    Quartz = _import_quartz()
    if Quartz is None:
        return []

    windows_info = Quartz.CGWindowListCopyWindowInfo(0, 0)
    if not windows_info:
        return []

    windows: list[_MacWindow] = []
    for w in windows_info:
        if not w.get("kCGWindowIsOnscreen"):
            continue
        layer = int(w.get("kCGWindowLayer", -1))
        if layer != 0:
            continue
        windows.append(_MacWindow(
            owner_name=str(w.get("kCGWindowOwnerName", "")),
            window_name=str(w.get("kCGWindowName", "")),
            window_id=int(w.get("kCGWindowNumber", 0)),
            owner_pid=int(w.get("kCGWindowOwnerPID", 0)),
            layer=layer,
        ))
    return windows


def _get_frontmost_pid() -> int | None:
    """Get the PID of the frontmost (active) application."""
    Quartz = _import_quartz()
    if Quartz is None:
        return None

    try:
        app = Quartz.NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.processIdentifier()
    except Exception:
        return None


def _strip_app_suffix(name: str) -> str:
    """Strip .exe or .app suffix for cross-platform target matching."""
    for suffix in (".exe", ".app"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def _resolve_macos_target(
    target: str, windows: list[_MacWindow] | None = None,
) -> tuple[list[str], str]:
    """Resolve target string to screencapture arguments.

    Returns:
        (screencapture_extra_args, description_message)

    Raises:
        ValueError: if the target cannot be resolved.
    """
    # Monitor targets
    if target == "primary" or (target.isdigit() and not target.startswith("0x")):
        index = 0 if target == "primary" else int(target)
        display = index + 1  # screencapture -D is 1-indexed
        return ["-x", "-D", str(display)], f"Monitor #{index}"

    # Window targets — need window list
    if windows is None:
        windows = _list_macos_windows()

    if target == "active":
        pid = _get_frontmost_pid()
        if pid is not None:
            for w in windows:
                if w.owner_pid == pid:
                    return (
                        ["-x", "-o", "-l", str(w.window_id)],
                        f"Active: {w.owner_name}",
                    )
        raise ValueError("Active window not found")

    # App name match (partial, case-insensitive)
    target_clean = _strip_app_suffix(target).lower()
    for w in windows:
        if target_clean in w.owner_name.lower():
            return (
                ["-x", "-o", "-l", str(w.window_id)],
                f"App: {w.owner_name}",
            )

    # Title match (partial, case-insensitive)
    for w in windows:
        if w.window_name and target_clean in w.window_name.lower():
            return (
                ["-x", "-o", "-l", str(w.window_id)],
                f"Title: {w.window_name}",
            )

    raise ValueError(f"Window or app not found: {target}")


def _capture_macos(target: str, dest_path: Path) -> CaptureResult:
    """Capture via screencapture on macOS."""
    if not shutil.which("screencapture"):
        return CaptureResult(ok=False, error="screencapture not found")

    # Monitor targets don't need Quartz; window targets do.
    is_monitor = target == "primary" or (
        target.isdigit() and not target.startswith("0x")
    )
    if not is_monitor and _import_quartz() is None:
        return CaptureResult(
            ok=False,
            error="pyobjc-framework-Quartz is required for window capture on macOS. "
                  "Install it with: pip install pyobjc-framework-Quartz",
        )

    try:
        sc_args, message = _resolve_macos_target(target)
    except ValueError as e:
        return CaptureResult(ok=False, error=str(e))

    cmd = ["screencapture"] + sc_args + [str(dest_path)]

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return CaptureResult(ok=False, error="screencapture timed out")
    except Exception as e:
        return CaptureResult(ok=False, error=str(e))

    if result.returncode != 0:
        stderr = result.stderr.strip()
        return CaptureResult(ok=False, error=stderr or "screencapture failed")

    if dest_path.exists() and dest_path.stat().st_size > 0:
        return CaptureResult(ok=True, image_path=dest_path, message=message)

    # screencapture returned 0 but no/empty file — likely permission denied
    return CaptureResult(
        ok=False,
        error="Capture produced empty output. "
              "Grant Screen Recording permission to your terminal app "
              "in System Settings > Privacy & Security > Screen Recording.",
    )


def sanitize_target_name(target: str) -> str:
    """Sanitize target string for use in filenames."""
    # Strip quotes
    name = target.strip("'\"")
    # Replace unsafe characters
    name = re.sub(r'[<>:"/\\|?*\s]+', "_", name)
    # Trim and lowercase
    name = name.strip("_").lower()
    return name or "unknown"

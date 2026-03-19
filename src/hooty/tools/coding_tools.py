"""Coding tools for Hooty — unified file operations, shell execution, and code exploration."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from agno.tools.coding import CodingTools

from hooty.tools.confirm import _confirm_action
from hooty.tools.dev_commands import DEV_TOOL_COMMANDS
from hooty.tools.shell_runner import ShellResult, _win_creation_flags, count_lines, log_command, run_with_timeout

logger = logging.getLogger("hooty")

_ALWAYS_IGNORE: frozenset[str] = frozenset({".git"})

_FALLBACK_IGNORE_DIRS: frozenset[str] = frozenset({
    "node_modules", "__pycache__", ".venv",
})


def _extract_gitignore_dirs(base_dir: Path) -> frozenset[str]:
    """Extract simple directory name patterns from .gitignore.

    Parses root .gitignore only. Extracts lines that are simple names
    (no wildcards, no path separators, no negation). Strips trailing '/'.
    """
    gitignore = base_dir / ".gitignore"
    if not gitignore.is_file():
        return frozenset()
    dirs: set[str] = set()
    try:
        lines = gitignore.read_text(errors="replace").splitlines()
    except OSError:
        return frozenset()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        name = line.rstrip("/")
        if not name or "/" in name or "*" in name or "?" in name or "[" in name:
            continue
        dirs.add(name)
    return frozenset(dirs)

# Shell utilities (Unix-specific, not shared with PowerShell)
_SHELL_UTILS = [
    # Network
    "curl", "wget",
    # Environment / system info
    "which", "env", "pwd", "date", "uname", "whoami", "id", "nproc",
    # Stream / text processing
    "tee", "xargs", "sed", "awk", "nl", "paste", "comm", "tac", "rev",
    "expand", "unexpand",
    # File info
    "file", "stat",
    # Path manipulation
    "basename", "dirname", "realpath", "readlink",
    # Checksum
    "md5sum", "sha256sum",
    # Archive / compression
    "tar", "zip", "unzip", "gzip", "gunzip", "zcat",
    "bzip2", "bunzip2", "xz", "unxz",
    # Managed packages (downloaded by pkg_manager)
    "rg",
]


def _find_git_usr_bin() -> str | None:
    """On Windows, locate Git's usr/bin directory for Unix utilities.

    Git for Windows bundles Unix tools (sed, awk, find, xargs, etc.) in
    ``<Git>/usr/bin``, but some install options only add ``<Git>/cmd`` to PATH.
    Detect the Git installation root from ``git.exe`` location and return
    the usr/bin path if it exists.
    """
    if sys.platform != "win32":
        return None
    git_exe = shutil.which("git")
    if not git_exe:
        return None
    # git.exe is typically at <Git>/cmd/git.exe
    git_dir = Path(git_exe).resolve().parent.parent
    usr_bin = git_dir / "usr" / "bin"
    if usr_bin.is_dir():
        return str(usr_bin)
    return None


_git_usr_bin: str | None = _find_git_usr_bin() if sys.platform == "win32" else None

# Append Git usr/bin to PATH so subprocess inherits it too
if _git_usr_bin and _git_usr_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _git_usr_bin
    logger.info("Added Git usr/bin to PATH: %s", _git_usr_bin)

# Append managed package directory to PATH so run_shell can access rg, etc.
from hooty.pkg_manager import pkg_dir as _pkg_dir_fn  # noqa: E402

_pkg_bin: str | None = _pkg_dir_fn()
if _pkg_bin and _pkg_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _pkg_bin
    logger.info("Added managed pkg dir to PATH: %s", _pkg_bin)

_available_commands_cache: dict[tuple[tuple[str, ...], str | None], list[str]] = {}


def _filter_available_commands(
    commands: list[str], base_dir: Path | None = None
) -> list[str]:
    """Filter command list to only those actually available.

    Results are cached per (commands, base_dir) key.  Call
    ``clear_command_cache()`` to invalidate.

    Checks three locations:
    1. PATH (via shutil.which)
    2. base_dir (working directory) — for project-local wrappers like ./mvnw, ./gradlew
    3. Git usr/bin (Windows only) — for Unix utilities bundled with Git

    shutil.which handles Windows PATHEXT automatically, so
    ``shutil.which("gradlew", path=base_dir)`` finds ``gradlew.bat`` on Windows.
    """
    cache_key = (tuple(commands), str(base_dir) if base_dir else None)
    cached = _available_commands_cache.get(cache_key)
    if cached is not None:
        return list(cached)

    available: list[str] = []
    base_str = str(base_dir) if base_dir else None
    for cmd in commands:
        if shutil.which(cmd) is not None:
            available.append(cmd)
        elif base_str and shutil.which(cmd, path=base_str) is not None:
            available.append(cmd)
        elif _git_usr_bin and shutil.which(cmd, path=_git_usr_bin) is not None:
            available.append(cmd)
    _available_commands_cache[cache_key] = available
    return available


def clear_command_cache() -> None:
    """Clear the cached command availability results."""
    _available_commands_cache.clear()


class HootyCodingTools(CodingTools):
    """CodingTools with configurable idle timeout and session-aware temp files."""

    def __init__(
        self,
        idle_timeout: int = 0,
        tmp_dir: str | None = None,
        session_dir: str | None = None,
        project_dir: str | None = None,
        add_dirs: list[str] | None = None,
        ignore_dirs: list[str] | None = None,
        snapshot_enabled: bool = False,
        shell_operators: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Shell operator policy (import here to avoid circular imports at module level)
        if shell_operators is None:
            from hooty.config import ShellOperatorsConfig
            shell_operators = ShellOperatorsConfig()
        self._shell_operators = shell_operators
        gitignore_path = self.base_dir / ".gitignore"
        if gitignore_path.is_file():
            base_ignore = _ALWAYS_IGNORE | _extract_gitignore_dirs(self.base_dir)
        else:
            base_ignore = _ALWAYS_IGNORE | _FALLBACK_IGNORE_DIRS
        self._ignore_dirs: frozenset[str] = base_ignore | frozenset(ignore_dirs or [])
        self.idle_timeout = idle_timeout
        self.tmp_dir = tmp_dir
        self.session_dir = session_dir
        self.project_dir = project_dir
        # Additional working directories (read+write allowed)
        self.additional_base_dirs: list[Path] = [
            Path(d).resolve() for d in (add_dirs or [])
        ]
        # Read-only directories beyond base_dir (grep/find/ls/read_file allowed)
        self.extra_read_dirs: list[Path] = []
        for d in (session_dir, project_dir):
            if d:
                self.extra_read_dirs.append(Path(d).resolve())
        # additional_base_dirs also need read access
        for d in self.additional_base_dirs:
            if d not in self.extra_read_dirs:
                self.extra_read_dirs.append(d)

        # File snapshot store for /diff and /rewind
        self._snapshot_store: Any = None
        if snapshot_enabled and session_dir:
            from hooty.file_snapshot import FileSnapshotStore
            self._snapshot_store = FileSnapshotStore(Path(session_dir))

        # Detect grep backend: rg (managed/PATH) > grep > python
        from hooty.pkg_manager import find_pkg
        rg_path = find_pkg("rg")
        if rg_path:
            self._grep_backend = "rg"
            self._rg_path = rg_path
        elif shutil.which("grep"):
            self._grep_backend = "grep"
            self._rg_path = None
        else:
            self._grep_backend = "python"
            self._rg_path = None

        # Register additional tools not present in base CodingTools
        self.register(self.apply_patch)
        self.register(self.move_file)
        self.register(self.create_directory)
        self.register(self.tree)

        # Extend instructions with new tool descriptions
        # Inserted before "## Best Practices" to stay within the Guidelines section
        if self.instructions and "## Best Practices" in self.instructions:
            extra = (
                "\n\n"
                "**apply_patch** - Apply changes to multiple files in a single call using "
                "Claude Code patch format (*** Begin Patch / *** End Patch).\n"
                "- Prefer this over multiple edit_file calls when changing several files at once.\n"
                "- Each operation specifies Add File, Update File, or Delete File.\n"
                "- Update File uses @@ context lines to anchor changes, then -/+ lines for removals/additions.\n\n"
                "**move_file** - Move or rename a file or directory.\n"
                "- Parent directories at the destination are created automatically.\n\n"
                "**create_directory** - Create a directory (including parents).\n"
                "- Use when you need to set up a directory structure before writing files.\n\n"
                "**tree** - Show recursive directory tree with hierarchical indentation.\n"
                "- Use to understand project structure; unlike ls, shows nested hierarchy.\n"
                "- Set depth to limit recursion (default 3). Output truncated at limit entries.\n\n"
            )
            self.instructions = self.instructions.replace(
                "## Best Practices", extra + "## Best Practices"
            )
        elif self.instructions:
            self.instructions += (
                "\n\n"
                "**apply_patch** - Apply changes to multiple files in a single call using "
                "Claude Code patch format (*** Begin Patch / *** End Patch).\n"
                "- Prefer this over multiple edit_file calls when changing several files at once.\n\n"
                "**move_file** - Move or rename a file or directory.\n"
                "- Parent directories at the destination are created automatically.\n\n"
                "**create_directory** - Create a directory (including parents).\n"
                "- Use when you need to set up a directory structure before writing files.\n\n"
                "**tree** - Show recursive directory tree with hierarchical indentation.\n"
                "- Use to understand project structure; unlike ls, shows nested hierarchy.\n"
                "- Set depth to limit recursion (default 3). Output truncated at limit entries."
            )

    def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        ignore_case: bool = False,
        include: Optional[str] = None,
        context: int = 0,
        limit: int = 100,
        ignore: bool = True,
    ) -> str:
        """Search file contents for a regex pattern. Returns matching lines with
        file paths and line numbers. Use the include parameter to filter by file
        type (e.g. '*.py'). Paths matching .gitignore patterns are skipped by default.

        :param str pattern: Regex pattern to search for.
        :param str path: Directory or file to search in (default: base directory).
        :param bool ignore_case: Case-insensitive matching.
        :param str include: Glob pattern to filter files (e.g. '*.py').
        :param int context: Number of context lines around each match.
        :param int limit: Maximum number of matches to return (default: 100).
        :param bool ignore: Skip paths under ignored directories (default: True).
        :return: Matching lines with file paths and line numbers, or an error message.
        """
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"

            # Resolve search path
            if path:
                safe, resolved_path = self._check_path(
                    path, self.base_dir, self.restrict_to_base_dir,
                )
                if not safe:
                    return f"Error: Path '{path}' is outside the allowed base directory"
            else:
                resolved_path = self.base_dir

            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"

            ignore_dirs = self._ignore_dirs if ignore else frozenset()

            # Dispatch to backend
            logger.debug("grep: backend=%s pattern=%r path=%s", self._grep_backend, pattern, resolved_path)
            if self._grep_backend == "rg":
                output = self._grep_rg(pattern, resolved_path, ignore_case, include, context, ignore_dirs)
            elif self._grep_backend == "grep":
                output = self._grep_cmd(pattern, resolved_path, ignore_case, include, context, ignore_dirs)
            else:
                output = self._grep_python(pattern, resolved_path, ignore_case, include, context, limit, ignore_dirs)

            if not output:
                return f"No matches found for pattern: {pattern}"

            # Make paths relative to base_dir and additional_base_dirs
            base_str = str(self.base_dir) + "/"
            output = output.replace(base_str, "")
            for add_dir in self.additional_base_dirs:
                add_str = str(add_dir) + "/"
                output = output.replace(add_str, "")

            # Enforce match limit (Python backend already limits internally)
            if self._grep_backend != "python":
                output_lines = output.split("\n")
                if len(output_lines) > limit:
                    output = "\n".join(output_lines[:limit])
                    output += f"\n[Results limited to {limit} matches]"

            # Apply truncation
            output, was_truncated, total_lines = self._truncate_output(output)
            if was_truncated:
                output += f"\n[Output truncated: {total_lines} lines total]"

            return output

        except subprocess.TimeoutExpired:
            return "Error: grep timed out after 30 seconds"
        except Exception as e:
            logger.debug("Error running grep: %s", e)
            return f"Error running grep: {e}"

    def _grep_rg(
        self,
        pattern: str,
        search_path: Path,
        ignore_case: bool,
        include: Optional[str],
        context: int,
        ignore_dirs: frozenset[str] = frozenset(),
    ) -> str:
        """Run ripgrep backend."""
        cmd = [self._rg_path, "-n", "--no-heading"]
        if ignore_case:
            cmd.append("-i")
        if context > 0:
            cmd.extend(["-C", str(context)])
        if include:
            cmd.extend(["--glob", include])
        for d in ignore_dirs:
            cmd.extend(["--glob", f"!{d}"])
        cmd.append(pattern)
        cmd.append(str(search_path))

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=str(self.base_dir),
            encoding="utf-8", errors="replace",
            creationflags=_win_creation_flags(),
        )
        if result.returncode == 1 and not result.stdout:
            return ""
        if result.returncode not in (0, 1) and result.stderr:
            return f"Error: {result.stderr.strip()}"
        return result.stdout

    def _grep_cmd(
        self,
        pattern: str,
        search_path: Path,
        ignore_case: bool,
        include: Optional[str],
        context: int,
        ignore_dirs: frozenset[str] = frozenset(),
    ) -> str:
        """Run system grep backend."""
        cmd = ["grep", "-rn"]
        if ignore_case:
            cmd.append("-i")
        if context > 0:
            cmd.extend(["-C", str(context)])
        if include:
            cmd.extend(["--include", include])
        for d in ignore_dirs:
            cmd.extend(["--exclude-dir", d])
        cmd.append(pattern)
        cmd.append(str(search_path))

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=str(self.base_dir),
            encoding="utf-8", errors="replace",
            creationflags=_win_creation_flags(),
        )
        if result.returncode == 1 and not result.stdout:
            return ""
        if result.returncode not in (0, 1) and result.stderr:
            return f"Error: {result.stderr.strip()}"
        return result.stdout

    def _grep_python(
        self,
        pattern: str,
        search_path: Path,
        ignore_case: bool,
        include: Optional[str],
        context: int,
        limit: int,
        ignore_dirs: frozenset[str] = frozenset(),
    ) -> str:
        """Pure-Python grep fallback — no external dependencies."""
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        results: list[str] = []
        match_count = 0

        # Collect files to search
        if search_path.is_file():
            files = [search_path]
        else:
            glob_pattern = include if include else "*"
            files = sorted(search_path.rglob(glob_pattern))

        for file_path in files:
            if not file_path.is_file():
                continue

            # Skip excluded directories (check relative path only)
            if ignore_dirs:
                try:
                    rel_parts = file_path.relative_to(search_path).parts
                except ValueError:
                    rel_parts = file_path.parts
                if any(part in ignore_dirs for part in rel_parts):
                    continue

            # Binary check: look for null bytes in first 8192 bytes
            try:
                with open(file_path, "rb") as fb:
                    chunk = fb.read(8192)
                if b"\x00" in chunk:
                    continue
            except (OSError, PermissionError):
                continue

            # Read and search
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue

            lines = content.splitlines()
            matched_indices: list[int] = []

            for i, line in enumerate(lines):
                if regex.search(line):
                    matched_indices.append(i)
                    match_count += 1
                    if match_count >= limit:
                        break

            if not matched_indices:
                continue

            # Compute relative path
            try:
                rel = file_path.relative_to(self.base_dir)
            except ValueError:
                rel = file_path

            if context == 0:
                # Simple output: only matching lines
                for idx in matched_indices:
                    results.append(f"{rel}:{idx + 1}:{lines[idx]}")
            else:
                # Context output with groups
                # Build set of line ranges to display
                ranges: list[tuple[int, int]] = []
                for idx in matched_indices:
                    start = max(0, idx - context)
                    end = min(len(lines) - 1, idx + context)
                    ranges.append((start, end))

                # Merge overlapping ranges
                merged: list[tuple[int, int]] = []
                for start, end in ranges:
                    if merged and start <= merged[-1][1] + 1:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                    else:
                        merged.append((start, end))

                matched_set = set(matched_indices)
                for gi, (start, end) in enumerate(merged):
                    if gi > 0:
                        results.append("--")
                    for li in range(start, end + 1):
                        sep = ":" if li in matched_set else "-"
                        results.append(f"{rel}{sep}{li + 1}{sep}{lines[li]}")

            if match_count >= limit:
                break

        return "\n".join(results)

    def ls(self, path: str | None = None, limit: int = 500, ignore: bool = True) -> str:
        """List directory contents sorted alphabetically. Directories are shown
        with a trailing /. Paths matching .gitignore patterns are skipped by default.

        :param str path: Directory to list (default: base directory).
        :param int limit: Maximum number of entries (default: 500).
        :param bool ignore: Skip directories matching ignore patterns (default: True).
        :return: Directory listing, one entry per line, or an error message.
        """
        try:
            if path:
                safe, resolved_path = self._check_path(path, self.base_dir, self.restrict_to_base_dir)
                if not safe:
                    return f"Error: Path '{path}' is outside the allowed base directory"
            else:
                resolved_path = self.base_dir

            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"
            if not resolved_path.is_dir():
                return f"Error: Not a directory: {path}"

            entries = []
            for entry in sorted(resolved_path.iterdir(), key=lambda p: p.name.lower()):
                if ignore and entry.is_dir() and entry.name in self._ignore_dirs:
                    continue
                suffix = "/" if entry.is_dir() else ""
                entries.append(entry.name + suffix)
                if len(entries) >= limit:
                    break

            if not entries:
                return f"Directory is empty: {path or '.'}"

            result = "\n".join(entries)
            if len(entries) >= limit:
                result += f"\n[Listing limited to {limit} entries]"
            return result

        except PermissionError:
            return f"Error: Permission denied: {path or '.'}"
        except Exception as e:
            logger.debug("Error listing directory: %s", e)
            return f"Error listing directory: {e}"

    def tree(
        self,
        path: str | None = None,
        depth: int = 3,
        limit: int = 200,
        ignore: bool = True,
    ) -> str:
        """Show recursive directory tree with indentation. Use this to understand
        project structure and module layout. Unlike ls (single directory listing),
        tree shows the nested hierarchy. Paths matching .gitignore patterns are
        skipped by default.

        :param str path: Root directory (default: base directory).
        :param int depth: Maximum recursion depth (default: 3).
        :param int limit: Maximum entries to display (default: 200).
        :param bool ignore: Skip ignored directories (default: True).
        :return: Tree visualization with connectors, or an error message.
        """
        try:
            if path:
                safe, resolved_path = self._check_path(path, self.base_dir, self.restrict_to_base_dir)
                if not safe:
                    return f"Error: Path '{path}' is outside the allowed base directory"
            else:
                resolved_path = self.base_dir

            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"
            if not resolved_path.is_dir():
                return f"Error: Not a directory: {path}"

            # Build tree lines
            lines: list[str] = []
            count = 0
            truncated_extra = 0

            try:
                root_label = str(resolved_path.relative_to(self.base_dir)) + "/"
            except ValueError:
                root_label = resolved_path.name + "/"
            if root_label == "./":
                root_label = resolved_path.name + "/"
            lines.append(root_label)

            def _walk(dir_path: Path, prefix: str, current_depth: int) -> None:
                nonlocal count, truncated_extra

                if current_depth > depth:
                    return

                try:
                    entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                except PermissionError:
                    return

                # Filter ignored dirs
                if ignore:
                    entries = [
                        e for e in entries
                        if not (e.is_dir() and e.name in self._ignore_dirs)
                    ]

                for i, entry in enumerate(entries):
                    is_last = i == len(entries) - 1
                    connector = "└── " if is_last else "├── "

                    if count >= limit:
                        truncated_extra += 1
                        continue

                    suffix = "/" if entry.is_dir() else ""
                    lines.append(f"{prefix}{connector}{entry.name}{suffix}")
                    count += 1

                    if entry.is_dir() and not entry.is_symlink():
                        extension = "    " if is_last else "│   "
                        _walk(entry, prefix + extension, current_depth + 1)

            _walk(resolved_path, "", 1)

            result = "\n".join(lines)
            if truncated_extra > 0:
                result += f"\n[Truncated: {truncated_extra} more entries not shown]"
            return result

        except PermissionError:
            return f"Error: Permission denied: {path or '.'}"
        except Exception as e:
            logger.debug("Error building tree: %s", e)
            return f"Error building tree: {e}"

    def find(self, pattern: str, path: str | None = None, limit: int = 500, ignore: bool = True) -> str:
        """Search for files by glob pattern (e.g. '*.py', '**/*.json'). Returns
        matching file paths relative to the working directory. Paths matching
        .gitignore patterns are skipped by default.

        :param str pattern: Glob pattern to match files (e.g. '*.py', '**/*.json').
        :param str path: Directory to search in (default: base directory).
        :param int limit: Maximum number of results (default: 500).
        :param bool ignore: Skip paths under ignored directories (default: True).
        :return: Matching file paths, one per line, or an error message.
        """
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"

            if path:
                safe, resolved_path = self._check_path(path, self.base_dir, self.restrict_to_base_dir)
                if not safe:
                    return f"Error: Path '{path}' is outside the allowed base directory"
            else:
                resolved_path = self.base_dir

            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"
            if not resolved_path.is_dir():
                return f"Error: Not a directory: {path}"

            matches = []
            for match in resolved_path.glob(pattern):
                if ignore:
                    try:
                        parts = match.relative_to(resolved_path).parts
                    except ValueError:
                        parts = ()
                    if any(part in self._ignore_dirs for part in parts):
                        continue
                try:
                    rel_path = match.relative_to(self.base_dir)
                except ValueError:
                    rel_path = None
                    for add_dir in self.additional_base_dirs:
                        try:
                            rel_path = match.relative_to(add_dir)
                            break
                        except ValueError:
                            continue
                    if rel_path is None:
                        rel_path = match  # absolute path fallback
                suffix = "/" if match.is_dir() else ""
                matches.append(str(rel_path) + suffix)

                if len(matches) >= limit:
                    break

            if not matches:
                return f"No files found matching pattern: {pattern}"

            result = "\n".join(sorted(matches))
            if len(matches) >= limit:
                result += f"\n[Results limited to {limit} entries]"
            return result

        except Exception as e:
            logger.debug("Error finding files: %s", e)
            return f"Error finding files: {e}"

    def _check_path(
        self, file_name: str, base_dir: Path, restrict_to_base_dir: bool = True,
    ) -> tuple[bool, Path]:
        """Extend path check to allow extra read-only directories."""
        safe, resolved = super()._check_path(file_name, base_dir, restrict_to_base_dir)
        if safe or not restrict_to_base_dir:
            return safe, resolved
        # Allow paths inside extra_read_dirs
        target = Path(file_name).resolve()
        for allowed in self.extra_read_dirs:
            try:
                target.relative_to(allowed)
                return True, target
            except ValueError:
                continue
        return False, base_dir

    def _check_command(self, command: str) -> Optional[str]:
        """Check shell command for safety: operators and command allowlist.

        Overrides the parent implementation to avoid its buggy path checks
        (no tilde expansion, no backslash/drive-letter detection).
        Path restrictions are NOT enforced here — file-level access control
        is handled by _check_path() for read/write/grep/find/ls, and
        shell commands are guarded by the user confirmation dialog (safe mode)
        or by the user's explicit choice to disable safe mode.

        Operator policy (configurable via tools.shell_operators in config.yaml):
        - Command substitution ($( ), ` `) — always blocked
        - Redirect (>, >>, <) — blocked by default, safe patterns (2>&1, N>/dev/null) allowed
        - Pipe (|) — allowed by default, each segment validated against allowlist
        - Chain (&&, ||, ;) — allowed by default, each segment validated against allowlist
        """
        if not self.restrict_to_base_dir:
            return None

        import shlex

        ops = self._shell_operators

        # 1. Command substitution — always blocked (bypasses allowlist validation)
        for pattern in ("$(", "`"):
            if pattern in command:
                return f"Error: Shell operator '{pattern}' is not allowed."

        # 2. Redirect validation
        if not ops.redirect:
            # Strip safe patterns (2>&1, N>/dev/null) before checking
            cleaned = re.sub(r'\d+>&\d+', '', command)
            cleaned = re.sub(r'\d+>/dev/null', '', cleaned)
            if re.search(r'[><]', cleaned):
                return (
                    "Error: Redirect operators (>, >>, <) are not allowed. "
                    "Set tools.shell_operators.redirect: true to enable."
                )

        # 3. Check disabled pipe/chain operators
        if not ops.pipe:
            if re.search(r'(?<!\|)\|(?!\|)', command):
                return "Error: Pipe operator '|' is not allowed."
        if not ops.chain:
            for op in ("&&", "||", ";"):
                if op in command:
                    return f"Error: Shell operator '{op}' is not allowed."

        # 4. Split command into segments by allowed pipe/chain operators
        delimiters: list[str] = []
        if ops.pipe:
            delimiters.append(r'(?<!\|)\|(?!\|)')  # | but not ||
        if ops.chain:
            delimiters.append(r'&&')
            delimiters.append(r'\|\|')
            delimiters.append(r';')

        if delimiters:
            segments = re.split('|'.join(delimiters), command)
        else:
            segments = [command]

        # 5. Validate each segment's leading command against the allowlist
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            # Strip redirect tokens before tokenizing
            clean_seg = re.sub(r'\d*[><]+\S*', '', segment).strip()
            if not clean_seg:
                continue
            try:
                tokens = shlex.split(clean_seg, posix=(os.name != "nt"))
            except ValueError:
                return "Error: Could not parse shell command."
            if self.allowed_commands is not None and tokens:
                cmd_base = Path(tokens[0]).name
                if cmd_base not in self.allowed_commands:
                    return f"Error: Command '{cmd_base}' is not in the allowed commands list."

        return None

    def read_file(self, file_path: str, offset: int = 0, limit: Optional[int] = None) -> str:
        """Read the contents of a file with line numbers. Use offset and limit to
        paginate large files. Always read a file before editing it.

        :param str file_path: Path to the file to read (relative to working directory).
        :param int offset: Line number to start reading from (0-indexed, default: 0).
        :param int limit: Maximum number of lines to read.
        :return: File contents with line numbers, or an error message.
        """
        if self.restrict_to_base_dir:
            try:
                target = Path(file_path).resolve()
                for allowed in self.extra_read_dirs:
                    try:
                        target.relative_to(allowed)
                        return self._read_session_file(target, offset, limit)
                    except ValueError:
                        continue
            except OSError:
                pass
        return super().read_file(file_path, offset, limit)

    def _is_in_allowed_base(self, resolved: Path) -> bool:
        """Check if resolved path is inside base_dir or any additional_base_dirs."""
        try:
            resolved.relative_to(self.base_dir)
            return True
        except ValueError:
            pass
        for d in self.additional_base_dirs:
            try:
                resolved.relative_to(d)
                return True
            except ValueError:
                continue
        return False

    def write_file(self, file_path: str, contents: str) -> str:
        """Create or overwrite a file with the given contents. Parent directories
        are created automatically. For modifying existing files, prefer edit_file.

        :param str file_path: Path to the file (relative to working directory).
        :param str contents: The full contents to write.
        :return: Success message with line count, or an error message.
        """
        if self.restrict_to_base_dir:
            try:
                resolved = (self.base_dir / file_path).resolve()
                if not self._is_in_allowed_base(resolved):
                    return f"Error: Path '{file_path}' is outside the allowed directories"
            except OSError:
                return f"Error: Path '{file_path}' is outside the allowed directories"
        if self._snapshot_store:
            self._snapshot_store.capture_before_write((self.base_dir / file_path).resolve())
        result = super().write_file(file_path, contents)
        if self._snapshot_store and not result.startswith("Error"):
            self._snapshot_store.record_after_write((self.base_dir / file_path).resolve())
        return result

    def edit_file(self, file_path: str, old_text: str, new_text: str) -> str:
        """Edit a file by replacing an exact text match with new text. The old_text
        must match exactly one location in the file, including whitespace and indentation.
        Returns a unified diff showing the change.

        :param str file_path: Path to the file (relative to working directory).
        :param str old_text: The exact text to find and replace — must match uniquely.
        :param str new_text: The replacement text.
        :return: Unified diff of the change, or an error message.
        """
        if self.restrict_to_base_dir:
            try:
                resolved = (self.base_dir / file_path).resolve()
                if not self._is_in_allowed_base(resolved):
                    return f"Error: Path '{file_path}' is outside the allowed directories"
            except OSError:
                return f"Error: Path '{file_path}' is outside the allowed directories"
        if self._snapshot_store:
            self._snapshot_store.capture_before_write((self.base_dir / file_path).resolve())
        result = super().edit_file(file_path, old_text, new_text)
        if self._snapshot_store and not result.startswith("Error"):
            self._snapshot_store.record_after_write((self.base_dir / file_path).resolve())
        return result

    def apply_patch(self, patch: str) -> str:
        """Apply a multi-file patch in Claude Code format. The patch must be wrapped in
        *** Begin Patch / *** End Patch markers. Supported operations:

        *** Add File: <path>      — create a new file (lines prefixed with +)
        *** Update File: <path>   — modify an existing file (@@ context, then -/+ lines)
        *** Delete File: <path>   — delete a file
        *** Move to: <new_path>   — inside Update File, rename after applying changes

        Example:
        *** Begin Patch
        *** Update File: src/main.py
        @@ def hello():
        -    print("old")
        +    print("new")
        *** End Patch

        :param str patch: The full patch text including Begin/End markers.
        :return: Summary of applied changes, or an error message.
        """
        from hooty.tools.apply_patch import (
            PatchApplyError,
            PatchParseError,
            apply_operations,
            parse_patch,
        )

        try:
            ops = parse_patch(patch)
        except PatchParseError as e:
            return f"Error: {e}"

        if not ops:
            return "No operations found in patch."

        # Validate all paths
        for op in ops:
            paths_to_check = [op.path] if hasattr(op, "path") else []
            if hasattr(op, "move_to") and op.move_to:
                paths_to_check.append(op.move_to)
            for p in paths_to_check:
                try:
                    resolved = (self.base_dir / p).resolve()
                    if not self._is_in_allowed_base(resolved):
                        return f"Error: Path '{p}' is outside the allowed directories"
                except OSError:
                    return f"Error: Invalid path '{p}'"

        # Snapshot before
        if self._snapshot_store:
            from hooty.tools.apply_patch import AddFile, DeleteFile, UpdateFile

            for op in ops:
                if isinstance(op, (UpdateFile, DeleteFile)):
                    target = (self.base_dir / op.path).resolve()
                    if target.exists():
                        self._snapshot_store.capture_before_write(target)
                if isinstance(op, UpdateFile) and op.move_to:
                    pass  # new path doesn't exist yet

        # Apply
        try:
            result = apply_operations(ops, self.base_dir)
        except PatchApplyError as e:
            return f"Error applying patch: {e}"

        # Snapshot after
        if self._snapshot_store:
            from hooty.tools.apply_patch import AddFile, UpdateFile

            for op in ops:
                if isinstance(op, AddFile):
                    target = (self.base_dir / op.path).resolve()
                    self._snapshot_store.record_after_write(target)
                elif isinstance(op, UpdateFile):
                    write_path = op.move_to or op.path
                    target = (self.base_dir / write_path).resolve()
                    self._snapshot_store.record_after_write(target)

        return result

    def move_file(self, src: str, dst: str) -> str:
        """Move or rename a file or directory. Paths are relative to the working directory.
        Parent directories of the destination are created automatically.

        :param str src: Source path.
        :param str dst: Destination path.
        :return: Success message, or an error message.
        """
        try:
            src_resolved = (self.base_dir / src).resolve()
            dst_resolved = (self.base_dir / dst).resolve()
        except OSError:
            return "Error: Invalid path"

        if not self._is_in_allowed_base(src_resolved):
            return f"Error: Source path '{src}' is outside the allowed directories"
        if not self._is_in_allowed_base(dst_resolved):
            return f"Error: Destination path '{dst}' is outside the allowed directories"
        if not src_resolved.exists():
            return f"Error: Source '{src}' does not exist"

        if self._snapshot_store:
            self._snapshot_store.capture_before_write(src_resolved)

        dst_resolved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_resolved), str(dst_resolved))

        if self._snapshot_store:
            self._snapshot_store.record_after_write(dst_resolved)

        return f"Moved '{src}' → '{dst}'"

    def create_directory(self, path: str) -> str:
        """Create a directory including all parent directories. Path is relative to
        the working directory. Returns an error if the directory already exists.

        :param str path: Directory path to create.
        :return: Success message, or an error message.
        """
        try:
            resolved = (self.base_dir / path).resolve()
        except OSError:
            return f"Error: Invalid path '{path}'"

        if not self._is_in_allowed_base(resolved):
            return f"Error: Path '{path}' is outside the allowed directories"
        if resolved.exists():
            return f"Directory already exists: {path}"

        resolved.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path}"

    def _read_session_file(self, target: Path, offset: int, limit: Optional[int]) -> str:
        """Read a file inside the session/project directory with the same formatting as CodingTools.

        If *target* is a directory, return a newline-separated listing of its
        immediate children so the LLM can discover files without ``ls`` or
        ``find`` (which are restricted to base_dir).
        """
        if not target.exists():
            return f"Error: File not found: {target}"
        if target.is_dir():
            entries = sorted(p.name for p in target.iterdir())
            if not entries:
                return f"(empty directory: {target})"
            return "\n".join(entries)
        if not target.is_file():
            return f"Error: Not a file: {target}"

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"Error: Permission denied: {target}"
        except Exception as e:
            return f"Error reading file: {e}"

        lines = content.splitlines()
        total_lines = len(lines)
        effective_limit = limit if limit is not None else self.max_lines
        selected = lines[offset : offset + effective_limit]

        num_width = len(str(offset + len(selected)))
        numbered = [
            f"{offset + i + 1:>{num_width}} | {line}"
            for i, line in enumerate(selected)
        ]
        result = "\n".join(numbered)

        shown_start = offset + 1
        shown_end = offset + len(selected)
        if shown_end < total_lines or offset > 0:
            result += f"\n[Showing lines {shown_start}-{shown_end} of {total_lines} total]"

        return result

    def run_shell(self, command: str, timeout: Optional[int] = None) -> str:
        """Execute a shell command and return its output (stdout + stderr combined).
        Commands run from the working directory. Long output is truncated and the
        full output is saved to a temp file whose path is included in the response.
        Use this for running tests, git operations, installing packages, and any
        other command-line task.

        stdin is connected to /dev/null. Interactive commands that wait for user
        input (e.g. bare ``python``, ``node``, ``pnpm`` without args) will
        receive immediate EOF and exit. Always use non-interactive flags or
        arguments.

        :param str command: The shell command to execute.
        :param int timeout: Timeout in seconds (default: toolkit shell_timeout).
        :return: Command output with exit code, or an error message.
        """
        path_error = self._check_command(command)
        if path_error:
            return path_error

        effective_timeout = timeout if timeout is not None else self.shell_timeout

        logger.debug("[run_shell] cmd=%r timeout=%d idle=%d", command, effective_timeout, self.idle_timeout)
        start = time.monotonic()
        try:
            result = run_with_timeout(
                command,
                cwd=str(self.base_dir),
                max_timeout=effective_timeout,
                idle_timeout=self.idle_timeout,
                shell=True,
                tmp_dir=self.tmp_dir,
            )
        except Exception as e:
            return f"Error running shell command: {e}"

        duration = time.monotonic() - start
        log_command(
            self.session_dir,
            command=command,
            returncode=result.returncode,
            duration=duration,
            timed_out=result.timed_out,
            idle_timed_out=result.idle_timed_out,
            output_file=result.output_file,
        )

        if result.interrupted:
            return f"Command interrupted by user. Partial output:\n{result.stdout}"
        if result.timed_out and not result.idle_timed_out:
            return f"Error: Command timed out after {effective_timeout} seconds"
        if result.idle_timed_out:
            return (
                f"Error: Command killed — no output for {self.idle_timeout} seconds "
                f"(idle timeout). Partial output:\n{result.stdout}"
            )

        return self._format_output(result)

    def _format_output(self, result: ShellResult) -> str:
        """Format shell result with truncation handling."""
        output = result.stdout
        if result.stderr:
            output += result.stderr

        header = f"Exit code: {result.returncode}\n"

        if result.output_file:
            # Large output from idle watch — file already exists, reuse for truncation
            self._temp_files.append(result.output_file)
            total = count_lines(result.output_file)
            truncated_output = output + (
                f"\n[Output truncated: {total} lines total. "
                f"Full output saved to: {result.output_file}]"
            )
            return header + truncated_output

        truncated_output, was_truncated, total_lines = self._truncate_output(output)

        if was_truncated:
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                suffix=".txt",
                prefix="coding_tools_",
                dir=self.tmp_dir,
            )
            tmp.write(output)
            tmp.close()
            self._temp_files.append(tmp.name)
            truncated_output += (
                f"\n[Output truncated: {total_lines} lines total. "
                f"Full output saved to: {tmp.name}]"
            )

        return header + truncated_output


class ConfirmableCodingTools(HootyCodingTools):
    """CodingTools with optional user confirmation before write/shell operations."""

    def __init__(self, confirm_ref: list[bool], **kwargs: Any) -> None:
        self._confirm_ref = confirm_ref
        super().__init__(**kwargs)

    def write_file(self, file_path: str, contents: str) -> str:
        if self._confirm_ref[0]:
            if not _confirm_action(file_path, title="\u26a0  Write File", tool_name="write_file"):
                return "User cancelled the file write operation."
        return super().write_file(file_path, contents)

    def edit_file(self, file_path: str, old_text: str, new_text: str) -> str:
        if self._confirm_ref[0]:
            if not _confirm_action(file_path, title="\u26a0  Edit File", tool_name="edit_file"):
                return "User cancelled the file edit operation."
        return super().edit_file(file_path, old_text, new_text)

    def apply_patch(self, patch: str) -> str:
        if self._confirm_ref[0]:
            if not _confirm_action("apply_patch", title="\u26a0  Apply Patch", tool_name="apply_patch"):
                return "User cancelled the patch operation."
        return super().apply_patch(patch)

    def move_file(self, src: str, dst: str) -> str:
        if self._confirm_ref[0]:
            if not _confirm_action(f"{src} → {dst}", title="\u26a0  Move File", tool_name="move_file"):
                return "User cancelled the move operation."
        return super().move_file(src, dst)

    def run_shell(self, command: str, timeout: Optional[int] = None) -> str:
        if self._confirm_ref[0]:
            if not _confirm_action(command, title="\u26a0  Shell", tool_name="run_shell"):
                return "User cancelled the operation."
        return super().run_shell(command, timeout)


class SelectiveCodingTools(ConfirmableCodingTools):
    """CodingTools with selectively blocked methods for sub-agents."""

    def __init__(self, confirm_ref: list[bool], blocked_tools: frozenset[str], **kwargs: Any) -> None:
        self._blocked_tools = blocked_tools
        super().__init__(confirm_ref=confirm_ref, **kwargs)

    def write_file(self, file_path: str, contents: str) -> str:
        if "write_file" in self._blocked_tools:
            return "Error: write_file is not available for this agent."
        return super().write_file(file_path, contents)

    def edit_file(self, file_path: str, old_text: str, new_text: str) -> str:
        if "edit_file" in self._blocked_tools:
            return "Error: edit_file is not available for this agent."
        return super().edit_file(file_path, old_text, new_text)

    def apply_patch(self, patch: str) -> str:
        if "apply_patch" in self._blocked_tools:
            return "Error: apply_patch is not available for this agent."
        return super().apply_patch(patch)

    def move_file(self, src: str, dst: str) -> str:
        if "move_file" in self._blocked_tools:
            return "Error: move_file is not available for this agent."
        return super().move_file(src, dst)

    def create_directory(self, path: str) -> str:
        if "create_directory" in self._blocked_tools:
            return "Error: create_directory is not available for this agent."
        return super().create_directory(path)

    def run_shell(self, command: str, timeout: Optional[int] = None) -> str:
        if "run_shell" in self._blocked_tools:
            return "Error: run_shell is not available for this agent."
        return super().run_shell(command, timeout)


class PlanModeCodingTools(HootyCodingTools):
    """Plan mode: write/edit blocked, shell requires confirmation.

    write_file / edit_file are unconditionally blocked — the LLM must call
    exit_plan_mode() to switch to coding mode before making changes.
    run_shell is kept with user confirmation for diagnostic/analysis use.

    When *auto_execute_ref* is set and ``True``, the transition to coding
    mode is pending — run_shell calls are also blocked so that the LLM
    does not execute the plan in planning mode.
    """

    _TRANSITION_MSG = (
        "Transition to coding mode is pending. "
        "Do not execute further actions in planning mode."
    )

    _WRITE_BLOCKED_MSG = (
        "write_file is not available in planning mode. "
        "To save plan content, use plans_create() or plans_update(). "
        "Call exit_plan_mode() to propose switching to coding mode, "
        "then implement changes there."
    )

    _EDIT_BLOCKED_MSG = (
        "edit_file is not available in planning mode. "
        "To update plan content, use plans_update(). "
        "Call exit_plan_mode() to propose switching to coding mode, "
        "then implement changes there."
    )

    _APPLY_PATCH_BLOCKED_MSG = (
        "apply_patch is not available in planning mode. "
        "Call exit_plan_mode() to propose switching to coding mode, "
        "then implement changes there."
    )

    _MOVE_FILE_BLOCKED_MSG = (
        "move_file is not available in planning mode. "
        "Call exit_plan_mode() to propose switching to coding mode, "
        "then implement changes there."
    )

    def __init__(
        self, auto_execute_ref: list[bool] | None = None, **kwargs: Any
    ) -> None:
        self._auto_execute_ref = auto_execute_ref
        super().__init__(**kwargs)

    def _is_transition_pending(self) -> bool:
        return bool(self._auto_execute_ref and self._auto_execute_ref[0])

    def write_file(self, file_path: str, contents: str) -> str:
        return self._WRITE_BLOCKED_MSG

    def edit_file(self, file_path: str, old_text: str, new_text: str) -> str:
        return self._EDIT_BLOCKED_MSG

    def apply_patch(self, patch: str) -> str:
        return self._APPLY_PATCH_BLOCKED_MSG

    def move_file(self, src: str, dst: str) -> str:
        return self._MOVE_FILE_BLOCKED_MSG

    def run_shell(self, command: str, timeout: Optional[int] = None) -> str:
        if self._is_transition_pending():
            return self._TRANSITION_MSG
        if not _confirm_action(command, title="\u26a0  Shell (Plan)", tool_name="run_shell"):
            return "User cancelled the operation."
        return super().run_shell(command, timeout)


def create_coding_tools(
    working_directory: str,
    confirm_ref: list[bool] | None = None,
    plan_mode: bool = False,
    auto_execute_ref: list[bool] | None = None,
    blocked_tools: frozenset[str] | None = None,
    extra_commands: list[str] | None = None,
    shell_timeout: int = 120,
    idle_timeout: int = 0,
    tmp_dir: str | None = None,
    session_dir: str | None = None,
    project_dir: str | None = None,
    add_dirs: list[str] | None = None,
    ignore_dirs: list[str] | None = None,
    snapshot_enabled: bool = False,
    shell_operators: Any = None,
) -> CodingTools:
    """Create coding tools scoped to the working directory."""
    base_dir = Path(working_directory).resolve()
    allowed = _filter_available_commands(
        [
            *CodingTools.DEFAULT_ALLOWED_COMMANDS,
            *DEV_TOOL_COMMANDS,
            *_SHELL_UTILS,
            *(extra_commands or []),
        ],
        base_dir=base_dir,
    )
    kwargs: dict[str, Any] = dict(
        base_dir=base_dir,
        all=True,
        restrict_to_base_dir=True,
        allowed_commands=allowed,
        shell_timeout=shell_timeout,
        idle_timeout=idle_timeout,
        tmp_dir=tmp_dir,
        session_dir=session_dir,
        project_dir=project_dir,
        add_dirs=add_dirs,
        ignore_dirs=ignore_dirs,
        snapshot_enabled=snapshot_enabled,
        shell_operators=shell_operators,
    )
    if plan_mode:
        return PlanModeCodingTools(auto_execute_ref=auto_execute_ref, **kwargs)
    if blocked_tools:
        return SelectiveCodingTools(
            confirm_ref=confirm_ref or [True],
            blocked_tools=blocked_tools,
            **kwargs,
        )
    if confirm_ref is not None:
        return ConfirmableCodingTools(confirm_ref=confirm_ref, **kwargs)
    return HootyCodingTools(**kwargs)

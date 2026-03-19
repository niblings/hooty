"""Tests for coding tools."""

from unittest.mock import MagicMock, patch

import pytest

from hooty.tools.coding_tools import (
    ConfirmableCodingTools,
    HootyCodingTools,
    PlanModeCodingTools,
    _FALLBACK_IGNORE_DIRS,
    _extract_gitignore_dirs,
    _filter_available_commands,
    _find_git_usr_bin,
    clear_command_cache,
    create_coding_tools,
)


def _make_python_grep_tools(tmp_path):
    """Create tools forced to use the Python grep backend."""
    clear_command_cache()
    with patch("hooty.pkg_manager.find_pkg", return_value=None), \
         patch("shutil.which", return_value=None):
        tools = HootyCodingTools(
            base_dir=tmp_path,
            all=True,
            restrict_to_base_dir=True,
        )
    assert tools._grep_backend == "python"
    return tools


class TestCreateCodingTools:
    """Test the create_coding_tools factory function."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_creates_coding_tools(self, tmp_path):
        tools = create_coding_tools(str(tmp_path))
        assert tools is not None
        assert tools.name == "coding_tools"

    def test_base_dir_is_set(self, tmp_path):
        tools = create_coding_tools(str(tmp_path))
        assert tools.base_dir == tmp_path

    def test_returns_hooty_coding_tools_without_confirm_ref(self, tmp_path):
        tools = create_coding_tools(str(tmp_path))
        assert type(tools) is HootyCodingTools

    def test_returns_confirmable_with_confirm_ref(self, tmp_path):
        confirm_ref = [False]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        assert isinstance(tools, ConfirmableCodingTools)

    def test_all_tools_enabled(self, tmp_path):
        tools = create_coding_tools(str(tmp_path))
        func_names = {f.name for f in tools.functions.values()}
        assert "read_file" in func_names
        assert "edit_file" in func_names
        assert "write_file" in func_names
        assert "run_shell" in func_names
        assert "grep" in func_names
        assert "find" in func_names
        assert "ls" in func_names

    def test_restrict_to_base_dir_enabled(self, tmp_path):
        tools = create_coding_tools(str(tmp_path))
        assert tools.restrict_to_base_dir is True

    def test_shell_timeout_forwarded(self, tmp_path):
        tools = create_coding_tools(str(tmp_path), shell_timeout=600)
        assert tools.shell_timeout == 600

    def test_idle_timeout_forwarded(self, tmp_path):
        tools = create_coding_tools(str(tmp_path), idle_timeout=30)
        assert tools.idle_timeout == 30

    def test_tmp_dir_forwarded(self, tmp_path):
        tools = create_coding_tools(str(tmp_path), tmp_dir="/tmp/test")
        assert tools.tmp_dir == "/tmp/test"

    def test_session_dir_forwarded(self, tmp_path):
        tools = create_coding_tools(str(tmp_path), session_dir="/tmp/session")
        assert tools.session_dir == "/tmp/session"


class TestHootyCodingTools:
    """Test HootyCodingTools run_shell override."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_run_shell_basic(self, tmp_path):
        tools = create_coding_tools(str(tmp_path))
        result = tools.run_shell("echo hello")
        assert "hello" in result
        assert "Exit code: 0" in result

    def test_run_shell_timeout(self, tmp_path):
        # Write a script to avoid shell operators blocked by _check_command
        script = tmp_path / "slow.py"
        script.write_text("import time\ntime.sleep(60)\n")
        tools = create_coding_tools(str(tmp_path), shell_timeout=2)
        result = tools.run_shell(f"python3 {script.name}")
        assert "timed out" in result.lower()
        assert "2 seconds" in result

    def test_run_shell_logs_command(self, tmp_path):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        tools = create_coding_tools(str(tmp_path), session_dir=str(session_dir))
        tools.run_shell("echo test")
        history = session_dir / "shell_history.jsonl"
        assert history.exists()

    def test_run_shell_blocks_command_substitution(self, tmp_path):
        tools = create_coding_tools(str(tmp_path))
        result = tools.run_shell("echo $(whoami)")
        assert "Error" in result
        assert "'$('" in result


class TestConfirmableCodingTools:
    """Test ConfirmableCodingTools confirmation behavior."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_write_file_cancelled(self, tmp_path):
        confirm_ref = [True]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        with patch("hooty.tools.coding_tools._confirm_action", return_value=False):
            result = tools.write_file("test.txt", "hello")
        assert "cancelled" in result.lower()

    def test_write_file_confirmed(self, tmp_path):
        confirm_ref = [True]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        with patch("hooty.tools.coding_tools._confirm_action", return_value=True):
            result = tools.write_file("test.txt", "hello")
        assert (tmp_path / "test.txt").read_text() == "hello"
        assert "cancelled" not in result.lower()

    def test_edit_file_cancelled(self, tmp_path):
        (tmp_path / "test.txt").write_text("old text")
        confirm_ref = [True]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        with patch("hooty.tools.coding_tools._confirm_action", return_value=False):
            result = tools.edit_file("test.txt", "old text", "new text")
        assert "cancelled" in result.lower()
        assert (tmp_path / "test.txt").read_text() == "old text"

    def test_edit_file_confirmed(self, tmp_path):
        (tmp_path / "test.txt").write_text("old text")
        confirm_ref = [True]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        with patch("hooty.tools.coding_tools._confirm_action", return_value=True):
            result = tools.edit_file("test.txt", "old text", "new text")
        assert (tmp_path / "test.txt").read_text() == "new text"
        assert "cancelled" not in result.lower()

    def test_run_shell_cancelled(self, tmp_path):
        confirm_ref = [True]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        with patch("hooty.tools.coding_tools._confirm_action", return_value=False):
            result = tools.run_shell("echo hello")
        assert "cancelled" in result.lower()

    def test_run_shell_confirmed(self, tmp_path):
        confirm_ref = [True]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        with patch("hooty.tools.coding_tools._confirm_action", return_value=True):
            result = tools.run_shell("echo hello")
        assert "hello" in result

    def test_no_confirm_when_safe_mode_off(self, tmp_path):
        confirm_ref = [False]
        tools = create_coding_tools(str(tmp_path), confirm_ref=confirm_ref)
        with patch("hooty.tools.coding_tools._confirm_action") as mock_confirm:
            tools.write_file("test.txt", "hello")
            mock_confirm.assert_not_called()


class TestReadFile:
    """Test read_file with line numbers."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_read_file_has_line_numbers(self, tmp_path):
        (tmp_path / "test.txt").write_text("line1\nline2\nline3\n")
        tools = create_coding_tools(str(tmp_path))
        result = tools.read_file("test.txt")
        assert "1" in result
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result


class TestGrep:
    """Test grep override with multiple backends."""

    # ── Python fallback tests (real files, no mocking of grep itself) ──

    def test_python_basic_match(self, tmp_path):
        (tmp_path / "hello.py").write_text("print('hello world')\nprint('goodbye')\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("hello")
        assert "hello.py" in result
        assert "hello world" in result

    def test_python_no_match(self, tmp_path):
        (tmp_path / "hello.py").write_text("print('hello')\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("zzz_no_match")
        assert "No matches found" in result

    def test_python_ignore_case(self, tmp_path):
        (tmp_path / "test.txt").write_text("Hello World\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("hello world", ignore_case=True)
        assert "Hello World" in result

    def test_python_include_filter(self, tmp_path):
        (tmp_path / "code.py").write_text("match_here\n")
        (tmp_path / "data.txt").write_text("match_here\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("match_here", include="*.py")
        assert "code.py" in result
        assert "data.txt" not in result

    def test_python_context_lines(self, tmp_path):
        lines = "\n".join(f"line{i}" for i in range(10))
        (tmp_path / "ctx.txt").write_text(lines)
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("line5", context=1)
        assert "line4" in result
        assert "line5" in result
        assert "line6" in result

    def test_python_skips_binary_files(self, tmp_path):
        (tmp_path / "binary.bin").write_bytes(b"match\x00binary")
        (tmp_path / "text.txt").write_text("match here\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("match")
        assert "text.txt" in result
        assert "binary.bin" not in result

    def test_python_limit(self, tmp_path):
        # Create a file with many matches
        content = "\n".join(f"match line {i}" for i in range(50))
        (tmp_path / "many.txt").write_text(content)
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("match", limit=5)
        lines = [x for x in result.strip().split("\n") if x and not x.startswith("[")]
        assert len(lines) <= 5

    def test_python_output_format(self, tmp_path):
        (tmp_path / "fmt.txt").write_text("alpha\nbeta\ngamma\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("beta")
        # Format: relative_path:line_number:content
        assert "fmt.txt:2:beta" in result

    def test_python_invalid_regex(self, tmp_path):
        (tmp_path / "test.txt").write_text("test\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("[invalid")
        assert "Error" in result

    def test_python_excludes_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("match_me\n")
        (tmp_path / "src.py").write_text("match_me\n")
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("match_me")
        assert "src.py" in result
        assert ".git" not in result

    def test_empty_pattern_error(self, tmp_path):
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("")
        assert "Error" in result

    def test_path_outside_base_dir_rejected(self, tmp_path):
        tools = _make_python_grep_tools(tmp_path)
        result = tools.grep("test", path="/etc")
        assert "Error" in result

    # ── Backend detection tests ──

    def test_backend_rg_detected(self, tmp_path):
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value="/usr/bin/rg"):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
            )
        assert tools._grep_backend == "rg"
        assert tools._rg_path == "/usr/bin/rg"

    def test_backend_grep_fallback(self, tmp_path):
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", side_effect=lambda cmd: "/usr/bin/grep" if cmd == "grep" else None):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
            )
        assert tools._grep_backend == "grep"

    def test_backend_python_fallback(self, tmp_path):
        tools = _make_python_grep_tools(tmp_path)
        assert tools._grep_backend == "python"

    # ── rg / grep command construction (mocked subprocess) ──

    def test_rg_command_construction(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value="/usr/local/bin/rg"):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
            )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "test.txt:1:hello\n"
        mock_result.stderr = ""

        with patch("hooty.tools.coding_tools.subprocess.run", return_value=mock_result) as mock_run:
            tools.grep("hello", ignore_case=True, include="*.txt", context=2)

        args = mock_run.call_args[0][0]
        assert args[0] == "/usr/local/bin/rg"
        assert "-n" in args
        assert "--no-heading" in args
        assert "-i" in args
        assert "-C" in args
        assert "2" in args
        assert "--glob" in args
        assert "*.txt" in args
        assert "hello" in args

    def test_grep_cmd_construction(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", side_effect=lambda cmd: "/usr/bin/grep" if cmd == "grep" else None):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
            )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "test.txt:1:hello\n"
        mock_result.stderr = ""

        with patch("hooty.tools.coding_tools.subprocess.run", return_value=mock_result) as mock_run:
            tools.grep("hello", ignore_case=True, include="*.py", context=3)

        args = mock_run.call_args[0][0]
        assert args[0] == "grep"
        assert "-rn" in args
        assert "-i" in args
        assert "-C" in args
        assert "3" in args
        assert "--include" in args
        assert "*.py" in args


class TestFindGitUsrBin:
    """Test _find_git_usr_bin() for Windows Git PATH discovery."""

    def test_returns_none_on_non_windows(self):
        with patch("hooty.tools.coding_tools.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert _find_git_usr_bin() is None

    def test_returns_none_when_git_not_found(self):
        with patch("hooty.tools.coding_tools.sys") as mock_sys, \
             patch("hooty.tools.coding_tools.shutil.which", return_value=None):
            mock_sys.platform = "win32"
            assert _find_git_usr_bin() is None

    def test_returns_usr_bin_when_exists(self, tmp_path):
        # Simulate Git installation: <Git>/cmd/git.exe and <Git>/usr/bin/
        git_dir = tmp_path / "Git"
        cmd_dir = git_dir / "cmd"
        cmd_dir.mkdir(parents=True)
        git_exe = cmd_dir / "git.exe"
        git_exe.write_text("")
        usr_bin = git_dir / "usr" / "bin"
        usr_bin.mkdir(parents=True)

        with patch("hooty.tools.coding_tools.sys") as mock_sys, \
             patch("hooty.tools.coding_tools.shutil.which", return_value=str(git_exe)):
            mock_sys.platform = "win32"
            result = _find_git_usr_bin()
            assert result == str(usr_bin)

    def test_returns_none_when_usr_bin_missing(self, tmp_path):
        # Git dir exists but no usr/bin
        git_dir = tmp_path / "Git"
        cmd_dir = git_dir / "cmd"
        cmd_dir.mkdir(parents=True)
        git_exe = cmd_dir / "git.exe"
        git_exe.write_text("")

        with patch("hooty.tools.coding_tools.sys") as mock_sys, \
             patch("hooty.tools.coding_tools.shutil.which", return_value=str(git_exe)):
            mock_sys.platform = "win32"
            assert _find_git_usr_bin() is None


class TestFilterAvailableCommandsGitUsrBin:
    """Test that _filter_available_commands falls back to Git usr/bin."""

    def setup_method(self):
        clear_command_cache()

    def test_finds_command_in_git_usr_bin(self, tmp_path):
        # Create a fake Git usr/bin with sed
        usr_bin = tmp_path / "usr" / "bin"
        usr_bin.mkdir(parents=True)
        (usr_bin / "sed").write_text("")

        def fake_which(cmd, path=None):
            if path == str(usr_bin) and cmd == "sed":
                return str(usr_bin / "sed")
            return None

        with patch("hooty.tools.coding_tools._git_usr_bin", str(usr_bin)), \
             patch("hooty.tools.coding_tools.shutil.which", side_effect=fake_which):
            result = _filter_available_commands(["sed"])
            assert "sed" in result

    def test_no_fallback_when_git_usr_bin_is_none(self):
        with patch("hooty.tools.coding_tools._git_usr_bin", None), \
             patch("hooty.tools.coding_tools.shutil.which", return_value=None):
            result = _filter_available_commands(["sed"])
            assert "sed" not in result


class TestIgnoreDirs:
    """Test ls/find/grep ignore directory filtering."""

    def _make_tools(self, tmp_path, ignore_dirs=None):
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", return_value=None):
            tools = HootyCodingTools(
                base_dir=tmp_path,
                all=True,
                restrict_to_base_dir=True,
                ignore_dirs=ignore_dirs,
            )
        return tools

    def _populate(self, tmp_path):
        """Create a directory tree with ignorable dirs."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("module\n")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\x00pyc")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("venv_lib\n")
        (tmp_path / "README.md").write_text("readme\n")

    # ── ls tests ──

    def test_ls_ignore_true_skips_ignored_dirs(self, tmp_path):
        self._populate(tmp_path)
        tools = self._make_tools(tmp_path)
        result = tools.ls(ignore=True)
        assert "node_modules/" not in result
        assert "__pycache__/" not in result
        assert ".venv/" not in result
        assert "src/" in result
        assert "README.md" in result

    def test_ls_ignore_false_shows_all(self, tmp_path):
        self._populate(tmp_path)
        tools = self._make_tools(tmp_path)
        result = tools.ls(ignore=False)
        assert "node_modules/" in result
        assert "__pycache__/" in result
        assert ".venv/" in result
        assert "src/" in result

    # ── find tests ──

    def test_find_ignore_true_skips_venv(self, tmp_path):
        self._populate(tmp_path)
        tools = self._make_tools(tmp_path)
        result = tools.find("**/*.py", ignore=True)
        assert "src/main.py" in result
        assert ".venv" not in result

    def test_find_ignore_false_includes_venv(self, tmp_path):
        self._populate(tmp_path)
        tools = self._make_tools(tmp_path)
        result = tools.find("**/*.py", ignore=False)
        assert "src/main.py" in result
        assert ".venv/lib.py" in result

    # ── Custom ignore_dirs ──

    def test_custom_ignore_dirs(self, tmp_path):
        (tmp_path / "custom_dir").mkdir()
        (tmp_path / "custom_dir" / "file.txt").write_text("data\n")
        (tmp_path / "keep_dir").mkdir()
        (tmp_path / "keep_dir" / "file.txt").write_text("data\n")
        tools = self._make_tools(tmp_path, ignore_dirs=["custom_dir"])
        result = tools.ls(ignore=True)
        assert "custom_dir/" not in result
        assert "keep_dir/" in result

    def test_custom_ignore_dirs_merged_with_defaults(self, tmp_path):
        # No .gitignore → fallback dirs used
        tools = self._make_tools(tmp_path, ignore_dirs=["my_cache"])
        assert "my_cache" in tools._ignore_dirs
        assert ".git" in tools._ignore_dirs  # _ALWAYS_IGNORE
        # _FALLBACK_IGNORE_DIRS used when no .gitignore
        for d in _FALLBACK_IGNORE_DIRS:
            assert d in tools._ignore_dirs

    # ── .gitignore extraction tests ──

    def test_extract_gitignore_dirs_basic(self, tmp_path):
        (tmp_path / ".gitignore").write_text("node_modules\n__pycache__\ndist\n")
        result = _extract_gitignore_dirs(tmp_path)
        assert result == frozenset({"node_modules", "__pycache__", "dist"})

    def test_extract_gitignore_dirs_skips_patterns(self, tmp_path):
        (tmp_path / ".gitignore").write_text(
            "*.pyc\n!important\npath/to/dir\n[Bb]uild\n?tmp\nnode_modules\n"
        )
        result = _extract_gitignore_dirs(tmp_path)
        assert result == frozenset({"node_modules"})

    def test_extract_gitignore_dirs_strips_trailing_slash(self, tmp_path):
        (tmp_path / ".gitignore").write_text("dist/\nbuild/\n")
        result = _extract_gitignore_dirs(tmp_path)
        assert result == frozenset({"dist", "build"})

    def test_extract_gitignore_dirs_missing_file(self, tmp_path):
        result = _extract_gitignore_dirs(tmp_path)
        assert result == frozenset()

    def test_extract_gitignore_dirs_skips_comments_and_blanks(self, tmp_path):
        (tmp_path / ".gitignore").write_text("# comment\n\n  \nvendor\n")
        result = _extract_gitignore_dirs(tmp_path)
        assert result == frozenset({"vendor"})

    def test_ignore_dirs_uses_gitignore_when_present(self, tmp_path):
        (tmp_path / ".gitignore").write_text("dist\ncoverage\n")
        tools = self._make_tools(tmp_path)
        assert "dist" in tools._ignore_dirs
        assert "coverage" in tools._ignore_dirs
        assert ".git" in tools._ignore_dirs  # _ALWAYS_IGNORE
        # _FALLBACK_IGNORE_DIRS should NOT be used when .gitignore exists
        # (unless they happen to be in .gitignore too)
        assert "__pycache__" not in tools._ignore_dirs
        assert ".venv" not in tools._ignore_dirs

    def test_ignore_dirs_uses_fallback_without_gitignore(self, tmp_path):
        # No .gitignore file
        tools = self._make_tools(tmp_path)
        assert ".git" in tools._ignore_dirs
        for d in _FALLBACK_IGNORE_DIRS:
            assert d in tools._ignore_dirs

    # ── grep Python fallback uses _ignore_dirs ──

    def test_grep_python_uses_ignore_dirs(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("findme\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.js").write_text("findme\n")
        tools = self._make_tools(tmp_path)
        assert tools._grep_backend == "python"
        result = tools.grep("findme")
        assert "src/app.py" in result
        assert "node_modules" not in result

    # ── grep ignore=False tests ──

    def test_grep_python_ignore_false_includes_ignored_dirs(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("findme\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.js").write_text("findme\n")
        tools = self._make_tools(tmp_path)
        assert tools._grep_backend == "python"
        result = tools.grep("findme", ignore=False)
        assert "src/app.py" in result
        assert "node_modules" in result

    def test_grep_rg_ignore_false_no_exclude_globs(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value="/usr/local/bin/rg"):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
            )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "test.txt:1:hello\n"
        mock_result.stderr = ""

        with patch("hooty.tools.coding_tools.subprocess.run", return_value=mock_result) as mock_run:
            tools.grep("hello", ignore=False)

        args = mock_run.call_args[0][0]
        # No --glob !dir patterns should be present
        for i, arg in enumerate(args):
            if arg == "--glob" and i + 1 < len(args):
                assert not args[i + 1].startswith("!"), f"Unexpected exclude glob: {args[i + 1]}"

    def test_grep_cmd_ignore_false_no_exclude_dirs(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", side_effect=lambda cmd: "/usr/bin/grep" if cmd == "grep" else None):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
            )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "test.txt:1:hello\n"
        mock_result.stderr = ""

        with patch("hooty.tools.coding_tools.subprocess.run", return_value=mock_result) as mock_run:
            tools.grep("hello", ignore=False)

        args = mock_run.call_args[0][0]
        assert "--exclude-dir" not in args

    # ── grep rg/cmd ignore_dirs tests ──

    def test_grep_rg_passes_ignore_dirs(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value="/usr/local/bin/rg"):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
                ignore_dirs=["my_custom"],
            )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "test.txt:1:hello\n"
        mock_result.stderr = ""

        with patch("hooty.tools.coding_tools.subprocess.run", return_value=mock_result) as mock_run:
            tools.grep("hello")

        args = mock_run.call_args[0][0]
        # Check that --glob !dir patterns are passed for ignore dirs
        glob_excludes = []
        for i, arg in enumerate(args):
            if arg == "--glob" and i + 1 < len(args) and args[i + 1].startswith("!"):
                glob_excludes.append(args[i + 1])
        assert "!.git" in glob_excludes
        assert "!my_custom" in glob_excludes

    def test_grep_cmd_passes_ignore_dirs(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", side_effect=lambda cmd: "/usr/bin/grep" if cmd == "grep" else None):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
                ignore_dirs=["my_custom"],
            )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "test.txt:1:hello\n"
        mock_result.stderr = ""

        with patch("hooty.tools.coding_tools.subprocess.run", return_value=mock_result) as mock_run:
            tools.grep("hello")

        args = mock_run.call_args[0][0]
        # Check that --exclude-dir patterns are passed
        exclude_dirs = []
        for i, arg in enumerate(args):
            if arg == "--exclude-dir" and i + 1 < len(args):
                exclude_dirs.append(args[i + 1])
        assert ".git" in exclude_dirs
        assert "my_custom" in exclude_dirs

    # ── grep add-dir path relativization ──

    def test_grep_output_relativizes_add_dir_paths(self, tmp_path):
        add_dir = tmp_path / "extra"
        add_dir.mkdir()
        (add_dir / "lib.py").write_text("findme\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", return_value=None):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
                add_dirs=[str(add_dir)],
            )
        assert tools._grep_backend == "python"
        result = tools.grep("findme", path=str(add_dir))
        # Path should be relative, not absolute
        assert "lib.py" in result
        assert str(add_dir) not in result

    # ── find add-dir tests ──

    def test_find_with_additional_base_dir(self, tmp_path):
        add_dir = tmp_path / "extra"
        add_dir.mkdir()
        (add_dir / "module.py").write_text("code\n")
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", return_value=None):
            tools = HootyCodingTools(
                base_dir=tmp_path, all=True, restrict_to_base_dir=True,
                add_dirs=[str(add_dir)],
            )
        result = tools.find("*.py", path=str(add_dir))
        assert "module.py" in result
        assert str(add_dir) not in result


class TestCheckCommand:
    """Test _check_command: segment validation, operator control, allowlist."""

    def _make_tools(self, tmp_path, cls=HootyCodingTools, shell_operators=None, **extra):
        clear_command_cache()
        with patch("hooty.pkg_manager.find_pkg", return_value=None), \
             patch("shutil.which", return_value=None):
            tools = cls(
                base_dir=tmp_path,
                all=True,
                restrict_to_base_dir=True,
                allowed_commands=["find", "ls", "cat", "echo", "grep", "head", "wc"],
                shell_operators=shell_operators,
                **extra,
            )
        return tools

    # ── Command substitution always blocked ──

    def test_command_substitution_always_blocked(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo $(whoami)")
        assert result is not None
        assert "'$('" in result

        result = tools._check_command("echo `whoami`")
        assert result is not None
        assert "'`'" in result

    # ── Pipe with segment validation (default: allowed) ──

    def test_pipe_with_allowed_commands(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("cat file.txt | grep pattern | head -20")
        assert result is None

    def test_pipe_blocks_unknown_command(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("cat file.txt | evil_cmd")
        assert result is not None
        assert "not in the allowed commands list" in result

    # ── Chain with segment validation (default: allowed) ──

    def test_chain_with_allowed_commands(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo hello && ls")
        assert result is None

    def test_chain_blocks_unknown_command(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo hello && evil_cmd")
        assert result is not None
        assert "not in the allowed commands list" in result

    def test_chain_or_operator(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo hello || echo fallback")
        assert result is None

    def test_chain_semicolon(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo hello; ls")
        assert result is None

    # ── Redirect (default: blocked) ──

    def test_redirect_blocked_by_default(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo foo > bar.txt")
        assert result is not None
        assert "Redirect" in result

    def test_redirect_append_blocked_by_default(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo foo >> bar.txt")
        assert result is not None
        assert "Redirect" in result

    def test_redirect_input_blocked_by_default(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("wc -l < file.txt")
        assert result is not None
        assert "Redirect" in result

    def test_redirect_allowed_when_enabled(self, tmp_path):
        from hooty.config import ShellOperatorsConfig
        ops = ShellOperatorsConfig(redirect=True)
        tools = self._make_tools(tmp_path, shell_operators=ops)
        result = tools._check_command("echo foo > bar.txt")
        assert result is None

    # ── Safe stderr redirect patterns (always allowed) ──

    def test_safe_stderr_redirect_2_to_1(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("find . -name test 2>&1")
        assert result is None

    def test_safe_stderr_redirect_dev_null(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("find . -name test 2>/dev/null")
        assert result is None

    # ── All operators disabled (legacy-compatible) ──

    def test_all_operators_disabled(self, tmp_path):
        from hooty.config import ShellOperatorsConfig
        ops = ShellOperatorsConfig(pipe=False, chain=False, redirect=False)
        tools = self._make_tools(tmp_path, shell_operators=ops)

        assert tools._check_command("cat file.txt | grep x") is not None
        assert tools._check_command("echo a && echo b") is not None
        assert tools._check_command("echo a || echo b") is not None
        assert tools._check_command("echo a; echo b") is not None
        assert tools._check_command("echo a > f.txt") is not None
        # Simple commands still work
        assert tools._check_command("echo hello") is None

    # ── Command allowlist always enforced ──

    def test_blocks_unknown_command(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("rm -rf /")
        assert result is not None
        assert "not in the allowed commands list" in result

    def test_allows_known_command(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("echo hello")
        assert result is None

    # ── Paths NOT restricted in run_shell (all modes) ──

    def test_allows_tilde_path(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("find ~/.m2 -name mvnw")
        assert result is None

    def test_allows_absolute_path_outside_base(self, tmp_path):
        tools = self._make_tools(tmp_path)
        result = tools._check_command("ls /etc")
        assert result is None

    def test_safe_mode_on_allows_tilde(self, tmp_path):
        tools = self._make_tools(tmp_path, cls=ConfirmableCodingTools, confirm_ref=[True])
        result = tools._check_command("find ~/.m2 -name mvnw")
        assert result is None

    def test_safe_mode_on_blocks_unknown_in_chain(self, tmp_path):
        tools = self._make_tools(tmp_path, cls=ConfirmableCodingTools, confirm_ref=[True])
        result = tools._check_command("echo hello && rm -rf /")
        assert result is not None
        assert "not in the allowed commands list" in result

    def test_plan_mode_allows_tilde(self, tmp_path):
        tools = self._make_tools(tmp_path, cls=PlanModeCodingTools)
        result = tools._check_command("find ~/.m2 -name mvnw")
        assert result is None

"""Tests for PowerShell tools."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hooty.tools.powershell_tools import (
    ConfirmablePowerShellTools,
    PowerShellTools,
    _check_allowed,
    _check_blocked,
    _detect_powershell,
    _truncate_output,
    create_powershell_tools,
)
from hooty.tools.shell_runner import ShellResult


# ---------------------------------------------------------------------------
# _detect_powershell
# ---------------------------------------------------------------------------


class TestDetectPowershell:
    """Test PowerShell executable detection."""

    def setup_method(self):
        _detect_powershell.cache_clear()

    def test_prefers_pwsh(self):
        with patch("hooty.tools.powershell_tools.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: (
                "/usr/bin/pwsh" if name == "pwsh" else None
            )
            assert _detect_powershell() == "/usr/bin/pwsh"

    def test_falls_back_to_powershell(self):
        with patch("hooty.tools.powershell_tools.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: (
                "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
                if name == "powershell"
                else None
            )
            result = _detect_powershell()
            assert result is not None
            assert "powershell" in result.lower()

    def test_returns_none_when_not_found(self):
        with patch(
            "hooty.tools.powershell_tools.shutil.which", return_value=None
        ):
            assert _detect_powershell() is None


# ---------------------------------------------------------------------------
# create_powershell_tools
# ---------------------------------------------------------------------------


class TestCreatePowershellTools:
    """Test the factory function."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.powershell_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_returns_none_when_no_powershell(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell", return_value=None
        ):
            assert create_powershell_tools(str(tmp_path)) is None

    def test_creates_tools_when_powershell_available(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell",
            return_value="/usr/bin/pwsh",
        ):
            tools = create_powershell_tools(str(tmp_path))
            assert tools is not None
            assert tools.name == "powershell_tools"

    def test_base_dir_is_set(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell",
            return_value="/usr/bin/pwsh",
        ):
            tools = create_powershell_tools(str(tmp_path))
            assert tools.base_dir == tmp_path

    def test_returns_plain_tools_without_confirm_ref(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell",
            return_value="/usr/bin/pwsh",
        ):
            tools = create_powershell_tools(str(tmp_path))
            assert type(tools) is PowerShellTools

    def test_returns_confirmable_with_confirm_ref(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell",
            return_value="/usr/bin/pwsh",
        ):
            tools = create_powershell_tools(str(tmp_path), confirm_ref=[False])
            assert isinstance(tools, ConfirmablePowerShellTools)

    def test_registers_run_powershell(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell",
            return_value="/usr/bin/pwsh",
        ):
            tools = create_powershell_tools(str(tmp_path))
            func_names = {f.name for f in tools.functions.values()}
            assert "run_powershell" in func_names

    def test_extra_commands_forwarded(self, tmp_path):
        with (
            patch(
                "hooty.tools.powershell_tools._detect_powershell",
                return_value="/usr/bin/pwsh",
            ),
            patch(
                "hooty.tools.powershell_tools._filter_available_commands",
                side_effect=lambda cmds, **kw: cmds,
            ),
        ):
            tools = create_powershell_tools(
                str(tmp_path), extra_commands=["terraform", "kubectl"]
            )
            assert "terraform" in tools._allowed
            assert "kubectl" in tools._allowed

    def test_shell_timeout_forwarded(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell",
            return_value="/usr/bin/pwsh",
        ):
            tools = create_powershell_tools(str(tmp_path), shell_timeout=600)
            assert tools.shell_timeout == 600

    def test_idle_timeout_forwarded(self, tmp_path):
        with patch(
            "hooty.tools.powershell_tools._detect_powershell",
            return_value="/usr/bin/pwsh",
        ):
            tools = create_powershell_tools(str(tmp_path), idle_timeout=30)
            assert tools.idle_timeout == 30


# ---------------------------------------------------------------------------
# PowerShellTools.run_powershell
# ---------------------------------------------------------------------------


class TestPowerShellTools:
    """Test command execution."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.powershell_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    @pytest.fixture()
    def tools(self, tmp_path):
        return PowerShellTools(
            powershell_path="/usr/bin/pwsh",
            base_dir=tmp_path,
        )

    def test_successful_command(self, tools):
        mock_result = ShellResult(
            stdout="hello world\n", stderr="", returncode=0,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "Exit code: 0" in result
        assert "hello world" in result

    def test_command_with_stderr(self, tools):
        mock_result = ShellResult(
            stdout="output\n", stderr="warning msg\n", returncode=0,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "output" in result
        assert "warning msg" in result

    def test_nonzero_exit_code(self, tools):
        mock_result = ShellResult(
            stdout="", stderr="error\n", returncode=1,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ):
            result = tools.run_powershell("Get-Content missing.txt")
        assert "Exit code: 1" in result

    def test_timeout(self, tools):
        mock_result = ShellResult(
            stdout="", stderr="", returncode=-1, timed_out=True,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "timed out" in result.lower()
        assert "120" in result

    def test_custom_timeout(self, tools):
        mock_result = ShellResult(
            stdout="", stderr="", returncode=-1, timed_out=True,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ):
            result = tools.run_powershell("Get-ChildItem", timeout=30)
        assert "30" in result

    def test_idle_timeout(self, tools):
        tools.idle_timeout = 10
        mock_result = ShellResult(
            stdout="partial", stderr="", returncode=-1,
            idle_timed_out=True,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "idle timeout" in result.lower()
        assert "partial" in result

    def test_run_with_timeout_args(self, tools, tmp_path):
        """Verify run_with_timeout is called with correct arguments."""
        mock_result = ShellResult(
            stdout="", stderr="", returncode=0,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ) as mock_run:
            tools.run_powershell("Get-ChildItem")
            mock_run.assert_called_once_with(
                ["/usr/bin/pwsh", "-NoProfile", "-NonInteractive", "-Command", "Get-ChildItem"],
                cwd=str(tmp_path),
                max_timeout=120,
                idle_timeout=0,
                shell=False,
                tmp_dir=None,
            )

    def test_output_truncation(self, tools):
        long_output = "\n".join(f"line {i}" for i in range(3000))
        mock_result = ShellResult(
            stdout=long_output, stderr="", returncode=0,
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "Output truncated" in result
        assert "3000" in result

    def test_general_exception(self, tools):
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            side_effect=OSError("exec failed"),
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "Error" in result
        assert "exec failed" in result

    def test_output_file_truncation(self, tools):
        mock_result = ShellResult(
            stdout="head content", stderr="", returncode=0,
            output_file="/tmp/run_001.log",
        )
        with patch(
            "hooty.tools.powershell_tools.run_with_timeout",
            return_value=mock_result,
        ), patch(
            "hooty.tools.powershell_tools.count_lines",
            return_value=5000,
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "Output truncated" in result
        assert "5000" in result
        assert "/tmp/run_001.log" in result
        assert "/tmp/run_001.log" in tools._temp_files


# ---------------------------------------------------------------------------
# Security checks
# ---------------------------------------------------------------------------


class TestPowerShellSecurity:
    """Test blocked patterns and allowed commands."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.powershell_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    @pytest.fixture()
    def tools(self, tmp_path):
        return PowerShellTools(
            powershell_path="/usr/bin/pwsh",
            base_dir=tmp_path,
        )

    # --- Blocked patterns ---

    @pytest.mark.parametrize(
        "cmd",
        [
            "Invoke-Expression 'malicious'",
            "iex ('payload')",
            "IEX ('payload')",
            "Start-Process calc.exe",
            "Invoke-WebRequest https://evil.com",
            "Invoke-RestMethod https://evil.com/api",
            "Set-ExecutionPolicy Unrestricted",
            "Add-Type -TypeDefinition $code",
            "[System.Reflection.Assembly]::Load('...')",
            "(New-Object Net.WebClient).DownloadString('http://x')",
            "(New-Object Net.WebClient).DownloadFile('http://x','y')",
        ],
    )
    def test_blocked_patterns(self, tools, cmd):
        result = tools.run_powershell(cmd)
        assert "blocked" in result.lower()

    def test_blocked_case_insensitive(self, tools):
        result = tools.run_powershell("INVOKE-EXPRESSION 'test'")
        assert "blocked" in result.lower()

    # --- Allowed commands ---

    @pytest.mark.parametrize(
        "cmd",
        [
            "Get-ChildItem",
            "get-childitem",
            "Get-Content file.txt",
            "Set-Content -Path out.txt -Value 'data'",
            "Select-String -Pattern TODO -Path *.py",
            "Test-Path ./file.txt",
            "Out-String",
            "Join-Path src hooty",
            "Split-Path -Leaf ./src/hooty/main.py",
            "Measure-Object -Line",
            "Group-Object Extension",
            "Compare-Object $a $b",
            "ConvertTo-Csv",
            "ConvertFrom-Csv",
        ],
    )
    def test_allowed_cmdlets_pass(self, cmd):
        assert _check_allowed(cmd) is None

    def test_dev_tool_commands_in_allowed_set(self, tmp_path):
        """Dev tool commands are included in the instance's allowed set."""
        with patch(
            "hooty.tools.powershell_tools._filter_available_commands",
            side_effect=lambda cmds, **kw: cmds,
        ):
            tools = PowerShellTools(
                powershell_path="/usr/bin/pwsh",
                base_dir=tmp_path,
            )
        for cmd in ["git", "python", "uv", "java", "go", "dotnet", "cargo", "node", "npm", "gradle"]:
            assert cmd in tools._allowed

    def test_extra_commands_included(self, tmp_path):
        """User-defined extra commands are included in the allowed set."""
        with patch(
            "hooty.tools.powershell_tools._filter_available_commands",
            side_effect=lambda cmds, **kw: cmds,
        ):
            tools = PowerShellTools(
                powershell_path="/usr/bin/pwsh",
                base_dir=tmp_path,
                extra_commands=["terraform", "kubectl", "helm"],
            )
        assert "terraform" in tools._allowed
        assert "kubectl" in tools._allowed
        assert "helm" in tools._allowed

    def test_disallowed_command(self):
        result = _check_allowed("Restart-Computer")
        assert result is not None
        assert "not in the allowed list" in result

    # --- Pipe handling ---

    def test_pipe_with_allowed_commands(self):
        assert _check_allowed("Get-ChildItem | Select-Object Name") is None

    def test_pipe_with_disallowed_segment(self):
        result = _check_allowed("Get-ChildItem | Out-GridView")
        assert result is not None
        assert "out-gridview" in result.lower()

    def test_multi_pipe_all_allowed(self):
        cmd = "Get-ChildItem -Recurse | Where-Object { $_.Length -gt 1000 } | Sort-Object Length"
        assert _check_allowed(cmd) is None

    # --- _check_blocked ---

    def test_check_blocked_returns_none_for_safe(self):
        assert _check_blocked("Get-ChildItem") is None

    def test_check_blocked_returns_error(self):
        result = _check_blocked("Invoke-Expression 'bad'")
        assert result is not None
        assert "blocked" in result.lower()


# ---------------------------------------------------------------------------
# _truncate_output
# ---------------------------------------------------------------------------


class TestTruncateOutput:
    """Test the output truncation helper."""

    def test_no_truncation_needed(self):
        text = "short output"
        result, was_truncated, total = _truncate_output(text)
        assert result == text
        assert was_truncated is False

    def test_line_truncation(self):
        text = "\n".join(f"line {i}" for i in range(3000))
        result, was_truncated, total = _truncate_output(text)
        assert was_truncated is True
        assert total == 3000
        assert result.count("\n") < 3000

    def test_byte_truncation(self):
        # Each line ~100 bytes, 1000 lines => ~100KB > 50KB limit
        text = "\n".join("x" * 100 for _ in range(1000))
        result, was_truncated, total = _truncate_output(text)
        assert was_truncated is True
        assert len(result.encode("utf-8")) <= 50_000


# ---------------------------------------------------------------------------
# ConfirmablePowerShellTools
# ---------------------------------------------------------------------------


class TestConfirmablePowerShellTools:
    """Test Safe mode confirmation behavior."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.powershell_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_cancel_when_safe_mode_on(self, tmp_path):
        tools = ConfirmablePowerShellTools(
            confirm_ref=[True],
            powershell_path="/usr/bin/pwsh",
            base_dir=tmp_path,
        )
        with patch(
            "hooty.tools.powershell_tools._confirm_action", return_value=False
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "cancelled" in result.lower()

    def test_proceed_when_confirmed(self, tmp_path):
        tools = ConfirmablePowerShellTools(
            confirm_ref=[True],
            powershell_path="/usr/bin/pwsh",
            base_dir=tmp_path,
        )
        mock_result = ShellResult(
            stdout="ok\n", stderr="", returncode=0,
        )
        with (
            patch(
                "hooty.tools.powershell_tools._confirm_action", return_value=True
            ),
            patch(
                "hooty.tools.powershell_tools.run_with_timeout",
                return_value=mock_result,
            ),
        ):
            result = tools.run_powershell("Get-ChildItem")
        assert "ok" in result

    def test_no_confirm_when_safe_mode_off(self, tmp_path):
        tools = ConfirmablePowerShellTools(
            confirm_ref=[False],
            powershell_path="/usr/bin/pwsh",
            base_dir=tmp_path,
        )
        mock_result = ShellResult(
            stdout="ok\n", stderr="", returncode=0,
        )
        with (
            patch(
                "hooty.tools.powershell_tools._confirm_action"
            ) as mock_confirm,
            patch(
                "hooty.tools.powershell_tools.run_with_timeout",
                return_value=mock_result,
            ),
        ):
            tools.run_powershell("Get-ChildItem")
            mock_confirm.assert_not_called()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    """Test atexit temp file cleanup."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.powershell_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_cleanup_temp_files(self, tmp_path):
        tools = PowerShellTools(
            powershell_path="/usr/bin/pwsh",
            base_dir=tmp_path,
        )
        # Create a fake temp file
        f = tmp_path / "test_tmp.txt"
        f.write_text("temp")
        tools._temp_files.append(str(f))
        tools._cleanup_temp_files()
        assert not f.exists()
        assert tools._temp_files == []

    def test_cleanup_missing_file(self, tmp_path):
        tools = PowerShellTools(
            powershell_path="/usr/bin/pwsh",
            base_dir=tmp_path,
        )
        tools._temp_files.append(str(tmp_path / "nonexistent.txt"))
        # Should not raise
        tools._cleanup_temp_files()
        assert tools._temp_files == []

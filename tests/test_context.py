"""Tests for Hooty context management."""

from hooty.context import (
    MAX_FILE_SIZE,
    context_fingerprint,
    find_global_instructions,
    find_project_instructions,
    load_context,
)


class TestFindGlobalInstructions:
    """Test global instruction file discovery."""

    def test_no_files(self, tmp_path):
        assert find_global_instructions(tmp_path) is None

    def test_hooty_md_only(self, tmp_path):
        (tmp_path / "hooty.md").write_text("# hooty", encoding="utf-8")
        result = find_global_instructions(tmp_path)
        assert result == tmp_path / "hooty.md"

    def test_instructions_md_only(self, tmp_path):
        (tmp_path / "instructions.md").write_text("# instructions", encoding="utf-8")
        result = find_global_instructions(tmp_path)
        assert result == tmp_path / "instructions.md"

    def test_both_files_picks_largest(self, tmp_path):
        (tmp_path / "hooty.md").write_text("small", encoding="utf-8")
        (tmp_path / "instructions.md").write_text("this is much larger content", encoding="utf-8")
        result = find_global_instructions(tmp_path)
        assert result == tmp_path / "instructions.md"

    def test_both_files_same_size_picks_hooty_md(self, tmp_path):
        content = "same content"
        (tmp_path / "hooty.md").write_text(content, encoding="utf-8")
        (tmp_path / "instructions.md").write_text(content, encoding="utf-8")
        result = find_global_instructions(tmp_path)
        # Same size: hooty.md has higher priority (first in list)
        assert result == tmp_path / "hooty.md"


class TestFindProjectInstructions:
    """Test project instruction file discovery."""

    def test_no_files(self, tmp_path):
        assert find_project_instructions(tmp_path) is None

    def test_agents_md_only(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# agents", encoding="utf-8")
        result = find_project_instructions(tmp_path)
        assert result == tmp_path / "AGENTS.md"

    def test_claude_md_only(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# claude", encoding="utf-8")
        result = find_project_instructions(tmp_path)
        assert result == tmp_path / "CLAUDE.md"

    def test_copilot_instructions_only(self, tmp_path):
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("# copilot", encoding="utf-8")
        result = find_project_instructions(tmp_path)
        assert result == gh_dir / "copilot-instructions.md"

    def test_multiple_files_picks_largest(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("small", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text("this is much larger content", encoding="utf-8")
        result = find_project_instructions(tmp_path)
        assert result == tmp_path / "CLAUDE.md"

    def test_multiple_files_same_size_picks_by_priority(self, tmp_path):
        content = "same content"
        (tmp_path / "AGENTS.md").write_text(content, encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(content, encoding="utf-8")
        result = find_project_instructions(tmp_path)
        # Same size: AGENTS.md has higher priority (first in list)
        assert result == tmp_path / "AGENTS.md"


class TestLoadContext:
    """Test context loading and merging."""

    def test_no_files(self, tmp_path):
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx is None
        assert info.global_path is None
        assert info.project_path is None

    def test_global_only_instructions_md(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_text("Be concise.", encoding="utf-8")
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx == "<global_instructions>\nBe concise.\n</global_instructions>"
        assert info.global_path == instructions
        assert info.global_size > 0
        assert info.global_lines == 1
        assert info.project_path is None

    def test_global_only_hooty_md(self, tmp_path):
        hooty = tmp_path / "hooty.md"
        hooty.write_text("Be helpful.", encoding="utf-8")
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx == "<global_instructions>\nBe helpful.\n</global_instructions>"
        assert info.global_path == hooty
        assert info.global_size > 0
        assert info.global_lines == 1
        assert info.project_path is None

    def test_global_picks_larger_file(self, tmp_path):
        (tmp_path / "hooty.md").write_text("short", encoding="utf-8")
        (tmp_path / "instructions.md").write_text(
            "this is the larger instructions file", encoding="utf-8"
        )
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert info.global_path == tmp_path / "instructions.md"

    def test_project_only(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (tmp_path / "CLAUDE.md").write_text("Use pytest.", encoding="utf-8")
        ctx, info = load_context(
            config_dir=config_dir,
            project_root=tmp_path,
        )
        assert ctx == "<project_instructions>\nUse pytest.\n</project_instructions>"
        assert info.global_path is None
        assert info.project_path == tmp_path / "CLAUDE.md"
        assert info.project_size > 0
        assert info.project_lines == 1

    def test_both_files_merged_with_xml_tags(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_text("Global rule.", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("Project rule.", encoding="utf-8")

        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert "<global_instructions>\nGlobal rule.\n</global_instructions>" in ctx
        assert "<project_instructions>\nProject rule.\n</project_instructions>" in ctx
        assert info.global_path == instructions
        assert info.project_path == tmp_path / "AGENTS.md"

    def test_empty_file_skipped(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_text("", encoding="utf-8")
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx is None
        assert info.global_path is None

    def test_whitespace_only_file_skipped(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_text("   \n\n  ", encoding="utf-8")
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx is None
        assert info.global_path is None

    def test_file_exceeding_size_limit_skipped(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_bytes(b"x" * (MAX_FILE_SIZE + 1))
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx is None
        assert info.global_path is None

    def test_file_at_size_limit_accepted(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_bytes(b"x" * MAX_FILE_SIZE)
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx is not None
        assert info.global_path == instructions

    def test_non_utf8_file_skipped(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_bytes(b"\x80\x81\x82\x83")
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx is None
        assert info.global_path is None

    def test_content_is_stripped(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_text("\n  Be concise.  \n\n", encoding="utf-8")
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert ctx == "<global_instructions>\nBe concise.\n</global_instructions>"

    def test_line_count_multiline(self, tmp_path):
        instructions = tmp_path / "instructions.md"
        instructions.write_text("line1\nline2\nline3\n", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("a\nb\n", encoding="utf-8")
        ctx, info = load_context(
            config_dir=tmp_path,
            project_root=tmp_path,
        )
        assert info.global_lines == 4
        assert info.project_lines == 3


class TestContextFingerprint:
    """Test context_fingerprint() for instruction file change detection."""

    def test_stable_when_no_changes(self, tmp_path):
        """Fingerprint is identical across consecutive calls with no changes."""
        (tmp_path / "CLAUDE.md").write_text("# Project", encoding="utf-8")
        fp1 = context_fingerprint(tmp_path, tmp_path)
        fp2 = context_fingerprint(tmp_path, tmp_path)
        assert fp1 == fp2

    def test_changes_on_file_modified(self, tmp_path):
        """Fingerprint changes when file content changes."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# v1", encoding="utf-8")
        fp_before = context_fingerprint(tmp_path, tmp_path)

        claude_md.write_text("# v2", encoding="utf-8")
        fp_after = context_fingerprint(tmp_path, tmp_path)

        assert fp_before != fp_after

    def test_changes_on_file_added(self, tmp_path):
        """Fingerprint changes when a new instruction file appears."""
        fp_before = context_fingerprint(tmp_path, tmp_path)

        (tmp_path / "AGENTS.md").write_text("# New", encoding="utf-8")
        fp_after = context_fingerprint(tmp_path, tmp_path)

        assert fp_before != fp_after

    def test_changes_on_file_removed(self, tmp_path):
        """Fingerprint changes when an instruction file is removed."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project", encoding="utf-8")
        fp_before = context_fingerprint(tmp_path, tmp_path)

        claude_md.unlink()
        fp_after = context_fingerprint(tmp_path, tmp_path)

        assert fp_before != fp_after

    def test_empty_when_no_files(self, tmp_path):
        """Fingerprint is (None, None) when no instruction files exist."""
        fp = context_fingerprint(tmp_path, tmp_path)
        assert fp == (None, None)

"""Tests for skill store — discovery, state persistence, instructions loading."""

import json
from pathlib import Path

from hooty.config import AppConfig, SkillsConfig
from hooty.skill_store import (
    SkillInfo,
    discover_skills,
    get_all_extra_paths,
    load_disabled_skills,
    load_extra_paths,
    load_global_extra_paths,
    load_skill_instructions,
    save_disabled_skills,
    save_extra_paths,
    save_global_extra_paths,
    skill_fingerprint,
)


def _make_config(tmp_path: Path, *, enabled: bool = True) -> AppConfig:
    """Create a minimal AppConfig pointing at tmp_path."""
    config_dir = tmp_path / ".hooty"
    config_dir.mkdir(parents=True, exist_ok=True)
    project_dir = config_dir / "projects" / "test-abc12345"
    project_dir.mkdir(parents=True, exist_ok=True)

    # Use a per-call subclass to avoid polluting AppConfig class properties
    class _TestConfig(AppConfig):
        @property
        def config_dir(self) -> Path:
            return config_dir

        @property
        def project_dir(self) -> Path:
            return project_dir

        @property
        def skills_state_path(self) -> Path:
            return project_dir / ".skills.json"

        @property
        def global_skills_state_path(self) -> Path:
            return config_dir / ".skills.json"

    return _TestConfig(
        working_directory=str(tmp_path / "project"),
        skills=SkillsConfig(enabled=enabled),
    )


def _create_skill(
    base_dir: Path,
    name: str,
    description: str = "A test skill",
    instructions: str = "Do the thing.",
    *,
    disable_model_invocation: bool = False,
    user_invocable: bool = True,
    scripts: list[str] | None = None,
    references: list[str] | None = None,
) -> Path:
    """Create a minimal skill directory with SKILL.md."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    fm_lines = ["---"]
    fm_lines.append(f"name: {name}")
    fm_lines.append(f"description: {description}")
    if disable_model_invocation:
        fm_lines.append("disable-model-invocation: true")
    if not user_invocable:
        fm_lines.append("user-invocable: false")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(instructions)

    (skill_dir / "SKILL.md").write_text("\n".join(fm_lines), encoding="utf-8")

    if scripts:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        for s in scripts:
            (scripts_dir / s).write_text(f"#!/bin/bash\necho {s}", encoding="utf-8")

    if references:
        refs_dir = skill_dir / "references"
        refs_dir.mkdir(exist_ok=True)
        for r in references:
            (refs_dir / r).write_text(f"# {r}\nReference content.", encoding="utf-8")

    return skill_dir


class TestBuiltinSkills:
    """Test builtin skill discovery from data/skills/ directory."""

    def test_builtin_skills_discovered(self, tmp_path):
        """discover_skills() finds explain-code and project-summary as builtin."""
        config = _make_config(tmp_path)
        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "explain-code" in by_name
        assert by_name["explain-code"].source == "builtin"
        assert "project-summary" in by_name
        assert by_name["project-summary"].source == "builtin"
        assert by_name["project-summary"].disable_model_invocation is True

    def test_builtin_overridable(self, tmp_path):
        """Project skills can override builtin skills of the same name."""
        config = _make_config(tmp_path)
        project_root = Path(config.working_directory)
        hooty_dir = project_root / ".hooty" / "skills"
        _create_skill(
            hooty_dir, "explain-code", "Custom explain",
            instructions="Custom version",
        )
        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert by_name["explain-code"].source == "project (.hooty)"
        assert by_name["explain-code"].instructions == "Custom version"

    def test_discover_builtin_skills(self, tmp_path):
        """Builtin skills in data/skills/ are discovered with source='builtin'."""
        config = _make_config(tmp_path)
        builtin_dir = Path(__file__).parent.parent / "src" / "hooty" / "data" / "skills"
        _create_skill(builtin_dir, "_test_builtin", "Test builtin skill")
        try:
            skills = discover_skills(config)
            by_name = {s.name: s for s in skills}
            assert "_test_builtin" in by_name
            assert by_name["_test_builtin"].source == "builtin"
        finally:
            # Clean up the test skill from the builtin directory
            import shutil
            shutil.rmtree(builtin_dir / "_test_builtin", ignore_errors=True)

    def test_builtin_overridden_by_global(self, tmp_path):
        """Global skills override same-name builtin skills."""
        config = _make_config(tmp_path)
        builtin_dir = Path(__file__).parent.parent / "src" / "hooty" / "data" / "skills"
        _create_skill(builtin_dir, "_test_override", "Builtin version", instructions="Builtin")
        global_dir = config.config_dir / "skills"
        _create_skill(global_dir, "_test_override", "Global version", instructions="Global")
        try:
            skills = discover_skills(config)
            by_name = {s.name: s for s in skills}
            assert "_test_override" in by_name
            assert by_name["_test_override"].source == "global"
            assert by_name["_test_override"].instructions == "Global"
        finally:
            import shutil
            shutil.rmtree(builtin_dir / "_test_override", ignore_errors=True)

    def test_builtin_overridden_by_project(self, tmp_path):
        """Project skills override same-name builtin skills."""
        config = _make_config(tmp_path)
        builtin_dir = Path(__file__).parent.parent / "src" / "hooty" / "data" / "skills"
        _create_skill(builtin_dir, "_test_proj_override", "Builtin", instructions="Builtin")
        project_root = Path(config.working_directory)
        hooty_dir = project_root / ".hooty" / "skills"
        _create_skill(hooty_dir, "_test_proj_override", "Project", instructions="Project")
        try:
            skills = discover_skills(config)
            by_name = {s.name: s for s in skills}
            assert "_test_proj_override" in by_name
            assert by_name["_test_proj_override"].source == "project (.hooty)"
            assert by_name["_test_proj_override"].instructions == "Project"
        finally:
            import shutil
            shutil.rmtree(builtin_dir / "_test_proj_override", ignore_errors=True)


class TestDiscoverSkills:
    """Test skill discovery from various directories."""

    def test_discover_global_skills(self, tmp_path):
        config = _make_config(tmp_path)
        global_dir = config.config_dir / "skills"
        _create_skill(global_dir, "code-review", "Review code quality")

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "code-review" in by_name
        assert by_name["code-review"].source == "global"

    def test_discover_project_claude_skills(self, tmp_path):
        config = _make_config(tmp_path)
        project_root = Path(config.working_directory)
        claude_dir = project_root / ".claude" / "skills"
        _create_skill(claude_dir, "api-design", "API conventions")

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "api-design" in by_name
        assert by_name["api-design"].source == "project (.claude)"

    def test_discover_project_github_skills(self, tmp_path):
        config = _make_config(tmp_path)
        project_root = Path(config.working_directory)
        github_dir = project_root / ".github" / "skills"
        _create_skill(github_dir, "ci-rules", "CI conventions")

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "ci-rules" in by_name
        assert by_name["ci-rules"].source == "project (.github)"

    def test_discover_project_hooty_skills(self, tmp_path):
        config = _make_config(tmp_path)
        project_root = Path(config.working_directory)
        hooty_dir = project_root / ".hooty" / "skills"
        _create_skill(hooty_dir, "deploy", "Deployment steps")

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "deploy" in by_name
        assert by_name["deploy"].source == "project (.hooty)"

    def test_same_name_last_wins(self, tmp_path):
        """Skills in .hooty override same-name skills in .claude."""
        config = _make_config(tmp_path)
        project_root = Path(config.working_directory)

        claude_dir = project_root / ".claude" / "skills"
        _create_skill(claude_dir, "review", "Claude review", instructions="Claude version")

        hooty_dir = project_root / ".hooty" / "skills"
        _create_skill(hooty_dir, "review", "Hooty review", instructions="Hooty version")

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "review" in by_name
        assert by_name["review"].instructions == "Hooty version"
        assert by_name["review"].source == "project (.hooty)"

    def test_extra_paths(self, tmp_path):
        extra_dir = tmp_path / "extra-skills"
        config = _make_config(tmp_path)
        # Store extra_paths in .skills.json (per-project)
        save_extra_paths(config, [str(extra_dir)])
        _create_skill(extra_dir, "external", "External skill")

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "external" in by_name

    def test_discover_with_scripts_and_references(self, tmp_path):
        config = _make_config(tmp_path)
        global_dir = config.config_dir / "skills"
        _create_skill(
            global_dir, "full-skill", "Full featured",
            scripts=["run.sh", "check.py"],
            references=["guide.md", "api.md"],
        )

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "full-skill" in by_name
        assert sorted(by_name["full-skill"].scripts) == ["check.py", "run.sh"]
        assert sorted(by_name["full-skill"].references) == ["api.md", "guide.md"]

    def test_discover_empty_directory(self, tmp_path):
        """With no user skills, only builtins are returned."""
        config = _make_config(tmp_path)
        skills = discover_skills(config)
        # Only builtin skills should be present
        assert all(s.source == "builtin" for s in skills)

    def test_disabled_skills_marked(self, tmp_path):
        config = _make_config(tmp_path)
        global_dir = config.config_dir / "skills"
        _create_skill(global_dir, "enabled-skill", "Enabled")
        _create_skill(global_dir, "disabled-skill", "Disabled")

        save_disabled_skills(config, {"disabled-skill"})

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert by_name["enabled-skill"].enabled is True
        assert by_name["disabled-skill"].enabled is False

    def test_frontmatter_flags(self, tmp_path):
        config = _make_config(tmp_path)
        global_dir = config.config_dir / "skills"
        _create_skill(global_dir, "manual", "Manual only", disable_model_invocation=True)
        _create_skill(global_dir, "auto", "Auto only", user_invocable=False)

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert by_name["manual"].disable_model_invocation is True
        assert by_name["manual"].user_invocable is True
        assert by_name["auto"].disable_model_invocation is False
        assert by_name["auto"].user_invocable is False

    def test_skip_dirs_without_skill_md(self, tmp_path):
        config = _make_config(tmp_path)
        global_dir = config.config_dir / "skills"
        global_dir.mkdir(parents=True, exist_ok=True)
        (global_dir / "not-a-skill").mkdir()
        (global_dir / "not-a-skill" / "README.md").write_text("hi")

        skills = discover_skills(config)
        names = {s.name for s in skills}
        assert "not-a-skill" not in names

    def test_skip_hidden_dirs(self, tmp_path):
        config = _make_config(tmp_path)
        global_dir = config.config_dir / "skills"
        global_dir.mkdir(parents=True, exist_ok=True)
        hidden = global_dir / ".hidden-skill"
        hidden.mkdir()
        (hidden / "SKILL.md").write_text("---\nname: hidden\n---\nHidden.")

        skills = discover_skills(config)
        names = {s.name for s in skills}
        assert "hidden" not in names


class TestDisabledSkillsPersistence:
    """Test .skills.json read/write."""

    def test_load_empty_when_no_file(self, tmp_path):
        config = _make_config(tmp_path)
        assert load_disabled_skills(config) == set()

    def test_save_and_load(self, tmp_path):
        config = _make_config(tmp_path)
        save_disabled_skills(config, {"skill-a", "skill-b"})

        loaded = load_disabled_skills(config)
        assert loaded == {"skill-a", "skill-b"}

    def test_save_creates_directory(self, tmp_path):
        config = _make_config(tmp_path)
        # Remove project dir to test creation
        import shutil
        shutil.rmtree(config.project_dir, ignore_errors=True)

        save_disabled_skills(config, {"test"})
        assert config.skills_state_path.exists()

    def test_load_handles_corrupt_json(self, tmp_path):
        config = _make_config(tmp_path)
        config.skills_state_path.write_text("not json", encoding="utf-8")
        assert load_disabled_skills(config) == set()

    def test_save_overwrites(self, tmp_path):
        config = _make_config(tmp_path)
        save_disabled_skills(config, {"a", "b"})
        save_disabled_skills(config, {"c"})

        loaded = load_disabled_skills(config)
        assert loaded == {"c"}

    def test_json_format(self, tmp_path):
        config = _make_config(tmp_path)
        save_disabled_skills(config, {"beta", "alpha"})

        data = json.loads(config.skills_state_path.read_text(encoding="utf-8"))
        assert data == {"disabled": ["alpha", "beta"]}  # Sorted

    def test_save_disabled_preserves_extra_paths(self, tmp_path):
        config = _make_config(tmp_path)
        save_extra_paths(config, ["/some/path"])
        save_disabled_skills(config, {"x"})

        data = json.loads(config.skills_state_path.read_text(encoding="utf-8"))
        assert data["disabled"] == ["x"]
        assert data["extra_paths"] == ["/some/path"]


class TestExtraPathsPersistence:
    """Test extra_paths in .skills.json."""

    def test_load_empty_when_no_file(self, tmp_path):
        config = _make_config(tmp_path)
        assert load_extra_paths(config) == []

    def test_save_and_load(self, tmp_path):
        config = _make_config(tmp_path)
        save_extra_paths(config, ["/a", "/b"])
        assert load_extra_paths(config) == ["/a", "/b"]

    def test_save_preserves_disabled(self, tmp_path):
        config = _make_config(tmp_path)
        save_disabled_skills(config, {"skill-a"})
        save_extra_paths(config, ["/ext"])

        data = json.loads(config.skills_state_path.read_text(encoding="utf-8"))
        assert data["disabled"] == ["skill-a"]
        assert data["extra_paths"] == ["/ext"]

    def test_load_handles_non_list(self, tmp_path):
        config = _make_config(tmp_path)
        config.skills_state_path.write_text(
            json.dumps({"extra_paths": "not-a-list"}), encoding="utf-8"
        )
        assert load_extra_paths(config) == []


class TestLoadSkillInstructions:
    """Test skill instructions loading with $ARGUMENTS substitution."""

    def test_basic_load(self):
        skill = SkillInfo(
            name="test", description="", source="global",
            source_path="/tmp/test", enabled=True,
            disable_model_invocation=False, user_invocable=True,
            instructions="Do the thing.",
        )
        assert load_skill_instructions(skill) == "Do the thing."

    def test_arguments_substitution(self):
        skill = SkillInfo(
            name="deploy", description="", source="global",
            source_path="/tmp/deploy", enabled=True,
            disable_model_invocation=True, user_invocable=True,
            instructions="Deploy to $ARGUMENTS environment.",
        )
        result = load_skill_instructions(skill, "staging")
        assert result == "Deploy to staging environment."

    def test_no_args_preserves_placeholder(self):
        skill = SkillInfo(
            name="test", description="", source="global",
            source_path="/tmp/test", enabled=True,
            disable_model_invocation=False, user_invocable=True,
            instructions="Run $ARGUMENTS tests.",
        )
        result = load_skill_instructions(skill)
        assert result == "Run $ARGUMENTS tests."


class TestGlobalExtraPathsPersistence:
    """Test global .skills.json extra_paths read/write."""

    def test_load_empty_when_no_file(self, tmp_path):
        config = _make_config(tmp_path)
        assert load_global_extra_paths(config) == []

    def test_save_and_load(self, tmp_path):
        config = _make_config(tmp_path)
        save_global_extra_paths(config, ["/global/a", "/global/b"])
        assert load_global_extra_paths(config) == ["/global/a", "/global/b"]

    def test_save_preserves_other_keys(self, tmp_path):
        config = _make_config(tmp_path)
        # Write a state with an existing key
        state_path = config.global_skills_state_path
        state_path.write_text(
            json.dumps({"disabled": ["x"], "extra_paths": []}), encoding="utf-8"
        )
        save_global_extra_paths(config, ["/new/path"])

        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["disabled"] == ["x"]
        assert data["extra_paths"] == ["/new/path"]

    def test_save_does_not_affect_project_state(self, tmp_path):
        config = _make_config(tmp_path)
        save_extra_paths(config, ["/project/path"])
        save_global_extra_paths(config, ["/global/path"])

        assert load_extra_paths(config) == ["/project/path"]
        assert load_global_extra_paths(config) == ["/global/path"]

    def test_load_handles_corrupt_json(self, tmp_path):
        config = _make_config(tmp_path)
        config.global_skills_state_path.write_text("not json", encoding="utf-8")
        assert load_global_extra_paths(config) == []

    def test_load_handles_non_list(self, tmp_path):
        config = _make_config(tmp_path)
        config.global_skills_state_path.write_text(
            json.dumps({"extra_paths": "string"}), encoding="utf-8"
        )
        assert load_global_extra_paths(config) == []


class TestGetAllExtraPaths:
    """Test get_all_extra_paths merging global + project."""

    def test_empty_when_no_files(self, tmp_path):
        config = _make_config(tmp_path)
        assert get_all_extra_paths(config) == []

    def test_global_only(self, tmp_path):
        config = _make_config(tmp_path)
        save_global_extra_paths(config, ["/global/a"])
        assert get_all_extra_paths(config) == ["/global/a"]

    def test_project_only(self, tmp_path):
        config = _make_config(tmp_path)
        save_extra_paths(config, ["/project/a"])
        assert get_all_extra_paths(config) == ["/project/a"]

    def test_merge_order_global_then_project(self, tmp_path):
        config = _make_config(tmp_path)
        save_global_extra_paths(config, ["/global/a"])
        save_extra_paths(config, ["/project/b"])
        assert get_all_extra_paths(config) == ["/global/a", "/project/b"]

    def test_deduplication(self, tmp_path):
        config = _make_config(tmp_path)
        save_global_extra_paths(config, ["/shared/path", "/global/only"])
        save_extra_paths(config, ["/shared/path", "/project/only"])
        result = get_all_extra_paths(config)
        assert result == ["/shared/path", "/global/only", "/project/only"]

    def test_discover_skills_uses_all_extra_paths(self, tmp_path):
        """discover_skills() picks up skills from both global and project extra_paths."""
        config = _make_config(tmp_path)

        global_extra = tmp_path / "global-extra"
        _create_skill(global_extra, "g-skill", "From global extra")
        save_global_extra_paths(config, [str(global_extra)])

        project_extra = tmp_path / "project-extra"
        _create_skill(project_extra, "p-skill", "From project extra")
        save_extra_paths(config, [str(project_extra)])

        skills = discover_skills(config)
        names = {s.name for s in skills}
        assert "g-skill" in names
        assert "p-skill" in names


class TestSkillFingerprint:
    """Test skill_fingerprint() for change detection."""

    def test_stable_when_no_changes(self, tmp_path):
        """Fingerprint is identical across consecutive calls with no changes."""
        config = _make_config(tmp_path)
        hooty_dir = Path(config.working_directory) / ".hooty" / "skills"
        _create_skill(hooty_dir, "my-skill", "A skill")

        fp1 = skill_fingerprint(config)
        fp2 = skill_fingerprint(config)
        assert fp1 == fp2

    def test_changes_on_skill_added(self, tmp_path):
        """Fingerprint changes when a new skill is added."""
        config = _make_config(tmp_path)
        hooty_dir = Path(config.working_directory) / ".hooty" / "skills"
        _create_skill(hooty_dir, "skill-a", "First skill")

        fp_before = skill_fingerprint(config)

        _create_skill(hooty_dir, "skill-b", "Second skill")
        fp_after = skill_fingerprint(config)

        assert fp_before != fp_after

    def test_changes_on_skill_removed(self, tmp_path):
        """Fingerprint changes when a skill is removed."""
        import shutil

        config = _make_config(tmp_path)
        hooty_dir = Path(config.working_directory) / ".hooty" / "skills"
        _create_skill(hooty_dir, "skill-a", "First skill")
        _create_skill(hooty_dir, "skill-b", "Second skill")

        fp_before = skill_fingerprint(config)

        shutil.rmtree(hooty_dir / "skill-b")
        fp_after = skill_fingerprint(config)

        assert fp_before != fp_after

    def test_changes_on_skill_md_edited(self, tmp_path):
        """Fingerprint changes when SKILL.md content is edited."""
        config = _make_config(tmp_path)
        hooty_dir = Path(config.working_directory) / ".hooty" / "skills"
        skill_dir = _create_skill(hooty_dir, "my-skill", "A skill", instructions="v1")

        fp_before = skill_fingerprint(config)

        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\n\nv2",
            encoding="utf-8",
        )
        fp_after = skill_fingerprint(config)

        assert fp_before != fp_after

    def test_nonempty_when_no_user_skills(self, tmp_path):
        """Fingerprint is a non-empty hex digest even with only builtins."""
        config = _make_config(tmp_path)
        fp = skill_fingerprint(config)
        assert isinstance(fp, str)
        assert len(fp) > 0  # builtins exist

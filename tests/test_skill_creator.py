"""Tests for the skill-creator skill — file structure, discovery, and content validation."""

from pathlib import Path

import yaml

from hooty.config import AppConfig, SkillsConfig
from hooty.skill_store import (
    discover_skills,
    load_skill_instructions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, *, enabled: bool = True) -> AppConfig:
    """Create a minimal AppConfig pointing at tmp_path."""
    config_dir = tmp_path / ".hooty"
    config_dir.mkdir(parents=True, exist_ok=True)
    project_dir = config_dir / "projects" / "test-abc12345"
    project_dir.mkdir(parents=True, exist_ok=True)

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


SKILL_CREATOR_DIR = Path(__file__).parent.parent / "src" / "hooty" / "data" / "skills" / "skill-creator"


# ---------------------------------------------------------------------------
# A. File structure validation
# ---------------------------------------------------------------------------

class TestSkillCreatorFileStructure:
    """Validate that skill-creator directory has the correct layout."""

    def test_skill_dir_exists(self):
        assert SKILL_CREATOR_DIR.is_dir(), f"Missing: {SKILL_CREATOR_DIR}"

    def test_skill_md_exists(self):
        assert (SKILL_CREATOR_DIR / "SKILL.md").is_file()

    def test_references_dir_exists(self):
        assert (SKILL_CREATOR_DIR / "references").is_dir()

    def test_skill_format_md_exists(self):
        assert (SKILL_CREATOR_DIR / "references" / "skill-format.md").is_file()


# ---------------------------------------------------------------------------
# B. SKILL.md frontmatter validation
# ---------------------------------------------------------------------------

class TestSkillCreatorFrontmatter:
    """Validate SKILL.md frontmatter fields."""

    @staticmethod
    def _parse_frontmatter() -> dict:
        content = (SKILL_CREATOR_DIR / "SKILL.md").read_text(encoding="utf-8")
        # Extract YAML between --- markers
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have YAML frontmatter between --- markers"
        return yaml.safe_load(parts[1])

    def test_name_field(self):
        fm = self._parse_frontmatter()
        assert fm["name"] == "skill-creator"

    def test_description_field(self):
        fm = self._parse_frontmatter()
        assert isinstance(fm["description"], str)
        assert len(fm["description"]) > 0

    def test_disable_model_invocation(self):
        fm = self._parse_frontmatter()
        assert fm["disable-model-invocation"] is True, (
            "skill-creator must be manual-only (disable-model-invocation: true)"
        )

    def test_no_user_invocable_false(self):
        """skill-creator should be user-invocable (default true, field absent or true)."""
        fm = self._parse_frontmatter()
        assert fm.get("user-invocable", True) is True


# ---------------------------------------------------------------------------
# C. SKILL.md instructions content validation
# ---------------------------------------------------------------------------

class TestSkillCreatorInstructions:
    """Validate that SKILL.md instructions contain required elements."""

    @staticmethod
    def _load_instructions() -> str:
        content = (SKILL_CREATOR_DIR / "SKILL.md").read_text(encoding="utf-8")
        parts = content.split("---", 2)
        return parts[2].strip()

    def test_has_arguments_placeholder(self):
        body = self._load_instructions()
        assert "$ARGUMENTS" in body, "Instructions must reference $ARGUMENTS"

    def test_has_get_skill_reference_call(self):
        body = self._load_instructions()
        assert 'get_skill_reference("skill-creator"' in body, (
            "Instructions must call get_skill_reference for skill-format.md"
        )

    def test_has_placement_guidance(self):
        """Instructions should guide placement (project vs global)."""
        body = self._load_instructions()
        assert ".hooty/skills/" in body
        assert "~/.hooty/skills/" in body

    def test_has_verify_step(self):
        body = self._load_instructions()
        assert "/skills reload" in body
        assert "/skills info" in body

    def test_has_numbered_steps(self):
        """Instructions should follow a step-by-step flow."""
        body = self._load_instructions()
        assert "## Step" in body or "## step" in body


# ---------------------------------------------------------------------------
# D. references/skill-format.md content validation
# ---------------------------------------------------------------------------

class TestSkillFormatReference:
    """Validate that references/skill-format.md covers all required topics."""

    @staticmethod
    def _load_reference() -> str:
        return (SKILL_CREATOR_DIR / "references" / "skill-format.md").read_text(
            encoding="utf-8"
        )

    def test_documents_frontmatter_fields(self):
        ref = self._load_reference()
        for field in ("name", "description", "disable-model-invocation", "user-invocable"):
            assert field in ref, f"Reference must document the '{field}' frontmatter field"

    def test_documents_arguments_placeholder(self):
        ref = self._load_reference()
        assert "$ARGUMENTS" in ref

    def test_documents_scripts_directory(self):
        ref = self._load_reference()
        assert "scripts/" in ref
        assert "get_skill_script" in ref

    def test_documents_references_directory(self):
        ref = self._load_reference()
        assert "references/" in ref
        assert "get_skill_reference" in ref

    def test_documents_progressive_discovery(self):
        ref = self._load_reference()
        assert "progressive discovery" in ref.lower() or "Progressive Discovery" in ref

    def test_documents_placement_priority(self):
        ref = self._load_reference()
        assert "global" in ref.lower()
        assert "project" in ref.lower()

    def test_references_builtin_examples(self):
        """Should mention existing builtin skills as examples."""
        ref = self._load_reference()
        assert "explain-code" in ref
        assert "project-summary" in ref


# ---------------------------------------------------------------------------
# E. Discovery integration — skill-creator detected as builtin skill
# ---------------------------------------------------------------------------

class TestSkillCreatorDiscovery:
    """Test that skill-creator is correctly discovered as a builtin skill."""

    def test_discovered_as_builtin(self, tmp_path):
        """skill-creator in data/skills/ is detected as builtin."""
        config = _make_config(tmp_path)
        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}

        assert "skill-creator" in by_name
        skill = by_name["skill-creator"]
        assert skill.source == "builtin"
        assert skill.disable_model_invocation is True
        assert skill.user_invocable is True
        assert skill.enabled is True

    def test_references_detected(self, tmp_path):
        """skill-creator references/skill-format.md is listed in references."""
        config = _make_config(tmp_path)
        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert "skill-format.md" in by_name["skill-creator"].references

    def test_no_scripts(self, tmp_path):
        """skill-creator should have no scripts/ directory."""
        config = _make_config(tmp_path)
        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert by_name["skill-creator"].scripts == []

    def test_overridable_by_project(self, tmp_path):
        """Project skill can override the builtin skill-creator."""
        config = _make_config(tmp_path)
        project_root = Path(config.working_directory)
        target = project_root / ".hooty" / "skills" / "skill-creator"
        target.mkdir(parents=True, exist_ok=True)

        import shutil
        shutil.copytree(SKILL_CREATOR_DIR, target, dirs_exist_ok=True)
        # Overwrite with custom instructions
        (target / "SKILL.md").write_text(
            "---\nname: skill-creator\ndescription: Custom\n"
            "disable-model-invocation: true\n---\nCustom version",
            encoding="utf-8",
        )

        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        assert by_name["skill-creator"].source == "project (.hooty)"
        assert by_name["skill-creator"].instructions == "Custom version"

    def test_instructions_load_with_arguments(self, tmp_path):
        """load_skill_instructions() substitutes $ARGUMENTS correctly."""
        config = _make_config(tmp_path)
        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        skill = by_name["skill-creator"]

        loaded = load_skill_instructions(skill, "lint-checker リント実行スキル")
        assert "$ARGUMENTS" not in loaded
        assert "lint-checker リント実行スキル" in loaded

    def test_instructions_no_arguments(self, tmp_path):
        """Without arguments, $ARGUMENTS placeholder is preserved."""
        config = _make_config(tmp_path)
        skills = discover_skills(config)
        by_name = {s.name: s for s in skills}
        skill = by_name["skill-creator"]

        loaded = load_skill_instructions(skill)
        assert "$ARGUMENTS" in loaded

"""Tests for hooty.review — data types, prompt builders, and JSON parser."""

from __future__ import annotations

import os

from hooty.review import (
    REVIEW_TYPES,
    FixRequest,
    build_fix_prompt,
    build_review_prompt,
    custom_review_type,
    describe_scope,
    parse_findings,
)


# ---------------------------------------------------------------------------
# describe_scope()
# ---------------------------------------------------------------------------


class TestDescribeScope:
    """Test scope description generation."""

    def test_working_dir_shows_dot(self, tmp_path):
        wd = str(tmp_path)
        assert describe_scope(wd, wd) == "."

    def test_file_shows_relative_path(self, tmp_path):
        f = tmp_path / "src" / "main.py"
        f.parent.mkdir(parents=True)
        f.touch()
        result = describe_scope(str(f), str(tmp_path))
        assert result == os.path.join("src", "main.py")

    def test_directory_has_trailing_slash(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        result = describe_scope(str(d), str(tmp_path))
        assert result == "src/"

    def test_nested_directory(self, tmp_path):
        d = tmp_path / "src" / "hooty" / "tools"
        d.mkdir(parents=True)
        result = describe_scope(str(d), str(tmp_path))
        assert result.endswith("/")
        assert "tools" in result


# ---------------------------------------------------------------------------
# build_review_prompt()
# ---------------------------------------------------------------------------


class TestBuildReviewPrompt:
    """Test review prompt generation."""

    def test_contains_scope(self, tmp_path):
        f = tmp_path / "main.py"
        f.touch()
        prompt = build_review_prompt(str(f), "main.py", str(tmp_path), REVIEW_TYPES[0])
        assert "main.py" in prompt

    def test_contains_focus(self, tmp_path):
        f = tmp_path / "main.py"
        f.touch()
        for rt in REVIEW_TYPES:
            prompt = build_review_prompt(str(f), "main.py", str(tmp_path), rt)
            assert rt.focus in prompt

    def test_file_prompt_uses_read_file(self, tmp_path):
        f = tmp_path / "main.py"
        f.touch()
        prompt = build_review_prompt(str(f), "main.py", str(tmp_path), REVIEW_TYPES[0])
        assert "read_file()" in prompt

    def test_directory_prompt_uses_find(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        prompt = build_review_prompt(str(d), "src/", str(tmp_path), REVIEW_TYPES[0])
        assert "find()" in prompt or "ls()" in prompt

    def test_contains_json_findings_format(self, tmp_path):
        f = tmp_path / "main.py"
        f.touch()
        prompt = build_review_prompt(str(f), "main.py", str(tmp_path), REVIEW_TYPES[0])
        assert "json:findings" in prompt

    def test_each_review_type_has_unique_key(self):
        keys = [rt.key for rt in REVIEW_TYPES]
        assert len(keys) == len(set(keys))

    def test_custom_review_type_wraps_user_input(self, tmp_path):
        f = tmp_path / "main.py"
        f.touch()
        rt = custom_review_type("any")
        prompt = build_review_prompt(str(f), "main.py", str(tmp_path), rt)
        assert "any" in prompt
        assert "user requested" in prompt.lower()

    def test_custom_review_type_preserves_user_text(self):
        rt = custom_review_type("check error handling in async code")
        assert "check error handling in async code" in rt.focus
        assert rt.key == "custom"


# ---------------------------------------------------------------------------
# parse_findings()
# ---------------------------------------------------------------------------


class TestParseFindings:
    """Test JSON findings extraction from agent response."""

    def test_valid_json(self):
        response = '''\
Some markdown review text here.

```json:findings
[
  {
    "id": 1,
    "severity": "Critical",
    "file": "src/hooty/repl.py",
    "line": 851,
    "title": "Buffer overflow",
    "suggestion": "Add validation"
  },
  {
    "id": 2,
    "severity": "Warning",
    "file": "src/hooty/config.py",
    "line": 64,
    "title": "Missing check",
    "suggestion": "Add range check"
  }
]
```
'''
        findings = parse_findings(response)
        assert len(findings) == 2
        assert findings[0]["id"] == 1
        assert findings[0]["severity"] == "Critical"
        assert findings[1]["file"] == "src/hooty/config.py"

    def test_empty_response(self):
        assert parse_findings("") == []

    def test_no_findings_block(self):
        assert parse_findings("Just some markdown text without findings.") == []

    def test_invalid_json(self):
        response = '''\
```json:findings
{invalid json here}
```
'''
        assert parse_findings(response) == []

    def test_non_list_json(self):
        response = '''\
```json:findings
{"key": "value"}
```
'''
        assert parse_findings(response) == []

    def test_findings_missing_required_fields(self):
        response = '''\
```json:findings
[
  {"id": 1, "severity": "Critical", "file": "foo.py", "title": "Good finding"},
  {"id": 2, "severity": "Warning"}
]
```
'''
        findings = parse_findings(response)
        assert len(findings) == 1
        assert findings[0]["id"] == 1

    def test_findings_with_extra_fields(self):
        response = '''\
```json:findings
[
  {
    "id": 1,
    "severity": "Critical",
    "file": "foo.py",
    "line": 10,
    "title": "Test",
    "suggestion": "Fix it",
    "extra_field": "ignored"
  }
]
```
'''
        findings = parse_findings(response)
        assert len(findings) == 1
        assert findings[0]["extra_field"] == "ignored"

    def test_findings_without_line(self):
        response = '''\
```json:findings
[
  {"id": 1, "severity": "Warning", "file": "foo.py", "title": "No line number"}
]
```
'''
        findings = parse_findings(response)
        assert len(findings) == 1
        assert "line" not in findings[0]


# ---------------------------------------------------------------------------
# build_fix_prompt()
# ---------------------------------------------------------------------------


class TestBuildFixPrompt:
    """Test fix prompt generation."""

    def test_single_finding_no_custom(self):
        req = FixRequest(
            finding={
                "id": 1,
                "severity": "Critical",
                "file": "repl.py",
                "line": 100,
                "title": "Bug found",
                "suggestion": "Fix the bug",
            },
        )
        prompt = build_fix_prompt([req])
        assert "repl.py:100" in prompt
        assert "Bug found" in prompt
        assert "Fix the bug" in prompt
        assert "Custom instruction" not in prompt

    def test_finding_with_custom_instruction(self):
        req = FixRequest(
            finding={
                "id": 1,
                "severity": "Warning",
                "file": "config.py",
                "line": 50,
                "title": "Missing validation",
                "suggestion": "Add check",
            },
            custom_instruction="Use pydantic validator instead",
        )
        prompt = build_fix_prompt([req])
        assert "config.py:50" in prompt
        assert "Use pydantic validator instead" in prompt
        assert "Custom instruction" in prompt

    def test_multiple_findings(self):
        reqs = [
            FixRequest(
                finding={
                    "id": 1,
                    "severity": "Critical",
                    "file": "a.py",
                    "line": 10,
                    "title": "Bug A",
                    "suggestion": "Fix A",
                },
            ),
            FixRequest(
                finding={
                    "id": 2,
                    "severity": "Warning",
                    "file": "b.py",
                    "line": 20,
                    "title": "Bug B",
                    "suggestion": "Fix B",
                },
                custom_instruction="Custom for B",
            ),
        ]
        prompt = build_fix_prompt(reqs)
        assert "a.py:10" in prompt
        assert "b.py:20" in prompt
        assert "Bug A" in prompt
        assert "Bug B" in prompt
        assert "Custom for B" in prompt

    def test_severity_icons(self):
        for severity, icon in [("Critical", "🔴"), ("Warning", "🟡"), ("Suggestion", "🔵")]:
            req = FixRequest(
                finding={
                    "id": 1,
                    "severity": severity,
                    "file": "x.py",
                    "title": "Test",
                },
            )
            prompt = build_fix_prompt([req])
            assert icon in prompt

    def test_finding_without_line(self):
        req = FixRequest(
            finding={
                "id": 1,
                "severity": "Warning",
                "file": "foo.py",
                "title": "No line",
                "suggestion": "Check",
            },
        )
        prompt = build_fix_prompt([req])
        assert "foo.py" in prompt
        # Should not have ":None"
        assert ":None" not in prompt

    def test_prompt_contains_instructions(self):
        req = FixRequest(
            finding={
                "id": 1,
                "severity": "Critical",
                "file": "x.py",
                "title": "Test",
            },
        )
        prompt = build_fix_prompt([req])
        assert "read_file()" in prompt
        assert "edit_file()" in prompt

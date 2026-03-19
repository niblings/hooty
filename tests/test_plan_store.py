"""Tests for Hooty plan store operations."""

from __future__ import annotations

import time
from pathlib import Path

from hooty.plan_store import (
    PLAN_STATUS_ACTIVE,
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_PENDING,
    PlanInfo,
    delete_plans,
    format_plan_for_display,
    get_plan,
    list_plans,
    save_plan,
    search_plans,
    update_plan_status,
)


def _make_config(tmp_path: Path):
    """Create a minimal AppConfig with config_dir pointing to tmp_path."""
    from hooty.config import AppConfig

    config = AppConfig()
    config.working_directory = str(tmp_path / "project")
    config.__class__ = type(
        "_TestConfig",
        (AppConfig,),
        {"config_dir": property(lambda self: tmp_path)},
    )
    return config


def test_save_plan_creates_file_with_frontmatter(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = save_plan(config, body="# My Plan\nDo stuff", session_id="sess-123", summary="Test plan")

    assert path is not None
    content = Path(path).read_text(encoding="utf-8")
    assert "---" in content
    assert "session_id: sess-123" in content
    assert "summary: Test plan" in content
    assert "# My Plan" in content


def test_save_plan_returns_none_for_empty(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert save_plan(config, body="", session_id="s1", summary="x") is None
    assert save_plan(config, body="   ", session_id="s1", summary="x") is None


def test_list_plans_newest_first(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    save_plan(config, body="Plan A", session_id="s1", summary="First")
    time.sleep(0.05)
    save_plan(config, body="Plan B", session_id="s1", summary="Second")

    plans = list_plans(config)
    assert len(plans) == 2
    assert plans[0].summary == "Second"
    assert plans[1].summary == "First"


def test_search_plans_case_insensitive(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    save_plan(config, body="Implement AUTH feature", session_id="s1", summary="Auth")
    save_plan(config, body="Fix database bug", session_id="s1", summary="DB fix")

    results = search_plans(config, "auth")
    assert len(results) == 1
    assert results[0].summary == "Auth"

    results = search_plans(config, "AUTH")
    assert len(results) == 1

    results = search_plans(config, "nonexistent")
    assert len(results) == 0


def test_get_plan_by_prefix(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    path = save_plan(config, body="Plan content", session_id="s1", summary="Get test")
    assert path is not None

    plan_id = Path(path).stem
    prefix = plan_id[:8]

    plan = get_plan(config, prefix)
    assert plan is not None
    assert plan.plan_id == plan_id
    assert plan.summary == "Get test"


def test_get_plan_not_found(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert get_plan(config, "nonexistent") is None


def test_delete_plans(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    p1 = save_plan(config, body="Plan 1", session_id="s1", summary="One")
    p2 = save_plan(config, body="Plan 2", session_id="s1", summary="Two")
    save_plan(config, body="Plan 3", session_id="s1", summary="Three")

    id1 = Path(p1).stem
    id2 = Path(p2).stem

    deleted = delete_plans(config, [id1, id2])
    assert deleted == 2
    assert len(list_plans(config)) == 1


def test_delete_plans_nonexistent(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert delete_plans(config, ["no-such-id"]) == 0


def test_format_plan_for_display(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    save_plan(config, body="X" * 2000, session_id="s1", summary="A short summary")
    plans = list_plans(config)
    assert len(plans) == 1

    info = format_plan_for_display(plans[0])
    assert info["short_id"] == plans[0].short_id
    assert "KB" in info["size"] or "B" in info["size"]
    assert info["summary"] == "A short summary"


def test_format_plan_long_summary() -> None:
    from datetime import datetime, timezone

    plan = PlanInfo(
        plan_id="a" * 36,
        short_id="a" * 8,
        file_path=Path("/tmp/test.md"),
        session_id="s1",
        summary="A" * 60,
        created_at=datetime.now(timezone.utc),
        size_bytes=512,
    )
    info = format_plan_for_display(plan)
    assert len(info["summary"]) <= 50
    assert info["summary"].endswith("...")


# ── Status field tests ──


def test_save_plan_has_active_status(tmp_path: Path) -> None:
    """New plans should have active status."""
    config = _make_config(tmp_path)
    path = save_plan(config, body="# Plan", session_id="s1", summary="Test")
    assert path is not None

    content = Path(path).read_text(encoding="utf-8")
    assert "status: active" in content

    plans = list_plans(config)
    assert plans[0].status == PLAN_STATUS_ACTIVE


def test_save_plan_cancels_old_active(tmp_path: Path) -> None:
    """Saving a new plan in the same session should cancel old active plans."""
    config = _make_config(tmp_path)
    save_plan(config, body="Plan A", session_id="s1", summary="First")
    time.sleep(0.05)
    save_plan(config, body="Plan B", session_id="s1", summary="Second")

    plans = list_plans(config)
    assert len(plans) == 2
    # Newest first
    assert plans[0].status == PLAN_STATUS_ACTIVE
    assert plans[0].summary == "Second"
    assert plans[1].status == PLAN_STATUS_CANCELLED
    assert plans[1].summary == "First"


def test_save_plan_different_session_not_cancelled(tmp_path: Path) -> None:
    """Plans from different sessions should not be cancelled."""
    config = _make_config(tmp_path)
    save_plan(config, body="Plan A", session_id="s1", summary="Session 1")
    time.sleep(0.05)
    save_plan(config, body="Plan B", session_id="s2", summary="Session 2")

    plans = list_plans(config)
    assert all(p.status == PLAN_STATUS_ACTIVE for p in plans)


def test_update_plan_status(tmp_path: Path) -> None:
    """update_plan_status should change the status in the file."""
    config = _make_config(tmp_path)
    path = save_plan(config, body="# Plan", session_id="s1", summary="Test")
    assert path is not None

    result = update_plan_status(config, path, PLAN_STATUS_COMPLETED)
    assert result is True

    plan = list_plans(config)[0]
    assert plan.status == PLAN_STATUS_COMPLETED

    # Verify file content
    content = Path(path).read_text(encoding="utf-8")
    assert "status: completed" in content


def test_update_plan_status_nonexistent(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert update_plan_status(config, "/no/such/file.md", PLAN_STATUS_COMPLETED) is False


def test_save_plan_special_chars_in_summary(tmp_path: Path) -> None:
    """Summary with YAML-special characters should round-trip safely."""
    config = _make_config(tmp_path)
    tricky_summaries = [
        "Fix: colon in summary",
        'Quotes "double" and \'single\'',
        "Hash # comment-like",
        "Braces {key: value} and [list]",
        "日本語のサマリー: テスト",
        "Multi: colon: values: here",
    ]
    for summary in tricky_summaries:
        path = save_plan(config, body="# Plan", session_id="s1", summary=summary)
        assert path is not None, f"save_plan failed for: {summary!r}"
        plans = list_plans(config)
        latest = plans[0]
        assert latest.summary == summary, (
            f"Round-trip failed for {summary!r}: got {latest.summary!r}"
        )
        # Clean up for next iteration
        delete_plans(config, [latest.plan_id])


def test_format_plan_includes_status_icon(tmp_path: Path) -> None:
    """format_plan_for_display should include status_icon."""
    config = _make_config(tmp_path)
    save_plan(config, body="# Plan", session_id="s1", summary="Test")
    plans = list_plans(config)
    info = format_plan_for_display(plans[0])
    assert "●" in info["status_icon"]
    assert info["status"] == PLAN_STATUS_ACTIVE


def test_update_plan_status_to_pending(tmp_path: Path) -> None:
    """active → pending transition should work."""
    config = _make_config(tmp_path)
    path = save_plan(config, body="# Plan", session_id="s1", summary="Test")
    assert path is not None

    result = update_plan_status(config, path, PLAN_STATUS_PENDING)
    assert result is True

    plan = list_plans(config)[0]
    assert plan.status == PLAN_STATUS_PENDING


def test_update_plan_status_to_cancelled(tmp_path: Path) -> None:
    """active → cancelled transition should work."""
    config = _make_config(tmp_path)
    path = save_plan(config, body="# Plan", session_id="s1", summary="Test")
    assert path is not None

    result = update_plan_status(config, path, PLAN_STATUS_CANCELLED)
    assert result is True

    plan = list_plans(config)[0]
    assert plan.status == PLAN_STATUS_CANCELLED


def test_pending_plan_not_cancelled_by_new_plan(tmp_path: Path) -> None:
    """Pending plans should not be auto-cancelled when creating a new plan."""
    config = _make_config(tmp_path)
    path = save_plan(config, body="Plan A", session_id="s1", summary="First")
    assert path is not None
    update_plan_status(config, path, PLAN_STATUS_PENDING)

    time.sleep(0.05)
    save_plan(config, body="Plan B", session_id="s1", summary="Second")

    plans = list_plans(config)
    assert len(plans) == 2
    statuses = {p.summary: p.status for p in plans}
    assert statuses["First"] == PLAN_STATUS_PENDING  # protected
    assert statuses["Second"] == PLAN_STATUS_ACTIVE


def test_pending_reactivate(tmp_path: Path) -> None:
    """pending → active transition should work."""
    config = _make_config(tmp_path)
    path = save_plan(config, body="# Plan", session_id="s1", summary="Test")
    assert path is not None
    update_plan_status(config, path, PLAN_STATUS_PENDING)

    result = update_plan_status(config, path, PLAN_STATUS_ACTIVE)
    assert result is True

    plan = list_plans(config)[0]
    assert plan.status == PLAN_STATUS_ACTIVE


def test_format_plan_pending_icon() -> None:
    """Pending plan should show ◷ icon."""
    from datetime import datetime, timezone

    plan = PlanInfo(
        plan_id="a" * 36,
        short_id="a" * 8,
        file_path=Path("/tmp/test.md"),
        session_id="s1",
        summary="Pending plan",
        created_at=datetime.now(timezone.utc),
        size_bytes=512,
        status=PLAN_STATUS_PENDING,
    )
    info = format_plan_for_display(plan)
    assert "◷" in info["status_icon"]


def test_format_plan_cancelled_icon() -> None:
    """Cancelled plan should show ✗ icon."""
    from datetime import datetime, timezone

    plan = PlanInfo(
        plan_id="a" * 36,
        short_id="a" * 8,
        file_path=Path("/tmp/test.md"),
        session_id="s1",
        summary="Cancelled plan",
        created_at=datetime.now(timezone.utc),
        size_bytes=512,
        status=PLAN_STATUS_CANCELLED,
    )
    info = format_plan_for_display(plan)
    assert "✗" in info["status_icon"]


def test_unknown_status_migrated_to_cancelled(tmp_path: Path) -> None:
    """Plans with unknown status should be read as 'cancelled'."""
    config = _make_config(tmp_path)
    path = save_plan(config, body="# Old Plan", session_id="s1", summary="Legacy")
    assert path is not None

    for unknown in ("superseded", "draft", "bogus"):
        content = Path(path).read_text(encoding="utf-8")
        content = content.replace("status: active", f"status: {unknown}")
        Path(path).write_text(content, encoding="utf-8")

        plans = list_plans(config)
        assert plans[0].status == PLAN_STATUS_CANCELLED, f"expected cancelled for {unknown!r}"

        # Reset for next iteration
        content = Path(path).read_text(encoding="utf-8")
        content = content.replace(f"status: {unknown}", "status: active")
        Path(path).write_text(content, encoding="utf-8")



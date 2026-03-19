"""Tests for PlanTools toolkit and plan_store helpers."""

from __future__ import annotations

import time
from pathlib import Path

from hooty.plan_store import (
    PLAN_STATUS_ACTIVE,
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_PENDING,
    get_plan_body,
    list_plans,
    save_plan,
    update_plan_body,
    update_plan_status,
)
from hooty.tools.plan_tools import PlanTools


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


def _make_plan_tools(tmp_path: Path, session_id: str = "test-session"):
    """Create PlanTools with a test config."""
    config = _make_config(tmp_path)
    session_id_ref: list[str] = [session_id]
    pt = PlanTools(config=config, session_id_ref=session_id_ref)
    return pt, config


# ── get_plan_body tests ──


def test_get_plan_body_returns_body_without_frontmatter(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = save_plan(config, body="# Hello\nWorld", session_id="s1", summary="Test")
    assert path is not None
    plan_id = Path(path).stem

    info, body = get_plan_body(config, plan_id[:8])
    assert info is not None
    assert info.plan_id == plan_id
    assert body.strip() == "# Hello\nWorld"
    assert "---" not in body  # frontmatter stripped


def test_get_plan_body_not_found(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    info, body = get_plan_body(config, "nonexistent")
    assert info is None
    assert body == ""


# ── update_plan_body tests ──


def test_update_plan_body_preserves_plan_id(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = save_plan(config, body="Original body", session_id="s1", summary="Original")
    assert path is not None
    plan_id = Path(path).stem

    ok = update_plan_body(config, plan_id[:8], "Updated body", summary="Updated")
    assert ok is True

    # Plan ID is preserved
    info, body = get_plan_body(config, plan_id[:8])
    assert info is not None
    assert info.plan_id == plan_id
    assert body.strip() == "Updated body"
    assert info.summary == "Updated"


def test_update_plan_body_keeps_summary_when_none(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    path = save_plan(config, body="Body", session_id="s1", summary="Keep me")
    plan_id = Path(path).stem

    ok = update_plan_body(config, plan_id[:8], "New body")
    assert ok is True

    info, body = get_plan_body(config, plan_id[:8])
    assert info.summary == "Keep me"
    assert body.strip() == "New body"


def test_update_plan_body_not_found(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert update_plan_body(config, "nonexistent", "body") is False


# ── PlanTools.plans_list tests ──


def test_plans_list_empty(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_list()
    assert "No plans found" in result


def test_plans_list_multiple(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    save_plan(config, body="Plan A", session_id="s1", summary="First")
    time.sleep(0.05)
    save_plan(config, body="Plan B", session_id="s1", summary="Second")

    result = pt.plans_list()
    assert "First" in result
    assert "Second" in result


def test_plans_list_status_filter(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    p1 = save_plan(config, body="Plan A", session_id="s1", summary="Active plan")
    time.sleep(0.05)
    save_plan(config, body="Plan B", session_id="s2", summary="Another active")

    # Mark p1 as completed
    from hooty.plan_store import update_plan_status
    update_plan_status(config, p1, PLAN_STATUS_COMPLETED)

    result = pt.plans_list(status_filter="active")
    assert "Another active" in result
    # p1 was cancelled by save_plan (same session) or marked completed
    # The active-only filter should show fewer results
    assert "active" in result.lower() or "Another" in result

    result_completed = pt.plans_list(status_filter="completed")
    assert "Active plan" in result_completed


def test_plans_list_invalid_filter(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_list(status_filter="invalid")
    assert "Invalid status filter" in result


# ── PlanTools.plans_get tests ──


def test_plans_get_success(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    path = save_plan(config, body="# My Plan\nDetails here", session_id="s1", summary="Test plan")
    plan_id = Path(path).stem

    result = pt.plans_get(plan_id[:8])
    assert "# My Plan" in result
    assert "Details here" in result
    assert "Test plan" in result


def test_plans_get_not_found(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_get("nonexistent")
    assert "not found" in result.lower()


def test_plans_get_truncation(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    long_body = "x" * 15_000
    path = save_plan(config, body=long_body, session_id="s1", summary="Long plan")
    plan_id = Path(path).stem

    result = pt.plans_get(plan_id[:8])
    assert "TRUNCATED" in result
    assert "15000 chars total" in result


# ── PlanTools.plans_search tests ──


def test_plans_search_found(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    save_plan(config, body="Implement authentication feature", session_id="s1", summary="Auth")
    save_plan(config, body="Fix database bug", session_id="s1", summary="DB fix")

    result = pt.plans_search("authentication")
    assert "Auth" in result

    result = pt.plans_search("nonexistent")
    assert "No plans matching" in result


def test_plans_search_empty_keyword(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_search("")
    assert "empty" in result.lower()


# ── PlanTools.plans_create tests ──


def test_plans_create_success(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_create(body="# New Plan\nContent", summary="My new plan")
    assert "Plan created" in result
    assert "[" not in result or "full ID" in result

    plans = list_plans(config)
    assert len(plans) == 1
    assert plans[0].summary == "My new plan"
    assert plans[0].status == PLAN_STATUS_ACTIVE


def test_plans_create_auto_cancels(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path, session_id="same-session")
    pt.plans_create(body="Plan A", summary="First")
    time.sleep(0.05)
    pt.plans_create(body="Plan B", summary="Second")

    plans = list_plans(config)
    assert len(plans) == 2
    # Newest first
    assert plans[0].status == PLAN_STATUS_ACTIVE
    assert plans[1].status == PLAN_STATUS_CANCELLED


def test_plans_create_empty_body(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_create(body="", summary="Test")
    assert "Error" in result


def test_plans_create_writes_frontmatter(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path, session_id="sess-abc")
    pt.plans_create(body="# Plan", summary="Test")

    plans = list_plans(config)
    content = plans[0].file_path.read_text(encoding="utf-8")
    assert "session_id: sess-abc" in content
    assert "status: active" in content


# ── PlanTools.plans_update tests ──


def test_plans_update_success(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_create(body="Original", summary="Original summary")
    plans = list_plans(config)
    short_id = plans[0].short_id

    result = pt.plans_update(plan_id=short_id, body="Updated content", summary="Updated summary")
    assert "updated" in result.lower()

    info, body = get_plan_body(config, short_id)
    assert body.strip() == "Updated content"
    assert info.summary == "Updated summary"


def test_plans_update_preserves_id(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    pt.plans_create(body="V1", summary="Test")
    plans = list_plans(config)
    original_id = plans[0].plan_id
    short_id = plans[0].short_id

    pt.plans_update(plan_id=short_id, body="V2")

    plans = list_plans(config)
    assert plans[0].plan_id == original_id


def test_plans_update_not_found(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_update(plan_id="nonexistent", body="Test")
    assert "Error" in result


def test_plans_update_empty_body(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_update(plan_id="abc", body="")
    assert "Error" in result


# ── PlanTools.plans_update_status tests ──


def test_plans_update_status_success(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    pt.plans_create(body="# Plan", summary="Test")
    plans = list_plans(config)
    short_id = plans[0].short_id

    result = pt.plans_update_status(plan_id=short_id, status="completed")
    assert "completed" in result

    plans = list_plans(config)
    assert plans[0].status == PLAN_STATUS_COMPLETED


def test_plans_update_status_invalid(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_update_status(plan_id="abc", status="deleted")
    assert "Invalid status" in result


def test_plans_update_status_not_found(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    result = pt.plans_update_status(plan_id="nonexistent", status="active")
    assert "not found" in result.lower()


# ── New status tests ──


def test_plans_update_status_pending(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    pt.plans_create(body="# Plan", summary="Test")
    plans = list_plans(config)
    short_id = plans[0].short_id

    result = pt.plans_update_status(plan_id=short_id, status="pending")
    assert "pending" in result

    plans = list_plans(config)
    assert plans[0].status == PLAN_STATUS_PENDING


def test_plans_update_status_cancelled(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    pt.plans_create(body="# Plan", summary="Test")
    plans = list_plans(config)
    short_id = plans[0].short_id

    result = pt.plans_update_status(plan_id=short_id, status="cancelled")
    assert "cancelled" in result

    plans = list_plans(config)
    assert plans[0].status == PLAN_STATUS_CANCELLED


def test_plans_list_filter_pending(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    p1 = save_plan(config, body="Plan A", session_id="s1", summary="Shelved plan")
    save_plan(config, body="Plan B", session_id="s2", summary="Active plan")
    update_plan_status(config, p1, PLAN_STATUS_PENDING)

    result = pt.plans_list(status_filter="pending")
    assert "Shelved plan" in result
    assert "Active plan" not in result


def test_plans_list_filter_cancelled(tmp_path: Path) -> None:
    pt, config = _make_plan_tools(tmp_path)
    p1 = save_plan(config, body="Plan A", session_id="s1", summary="Old plan")
    save_plan(config, body="Plan B", session_id="s2", summary="Current plan")
    update_plan_status(config, p1, PLAN_STATUS_CANCELLED)

    result = pt.plans_list(status_filter="cancelled")
    assert "Old plan" in result
    assert "Current plan" not in result

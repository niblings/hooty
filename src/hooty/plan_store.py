"""Plan storage — project-scoped plan CRUD and migration."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from hooty.text_utils import truncate_display

if TYPE_CHECKING:
    from hooty.config import AppConfig

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_COMPLETED = "completed"
PLAN_STATUS_PENDING = "pending"
PLAN_STATUS_CANCELLED = "cancelled"

PLAN_STATUS_ICONS: dict[str, str] = {
    PLAN_STATUS_ACTIVE: "[#50fa7b]●[/#50fa7b]",
    PLAN_STATUS_COMPLETED: "[cyan]✓[/cyan]",
    PLAN_STATUS_PENDING: "[yellow]◷[/yellow]",
    PLAN_STATUS_CANCELLED: "[red]✗[/red]",
}


@dataclass
class PlanInfo:
    """Metadata for a saved plan file."""

    plan_id: str
    short_id: str
    file_path: Path
    session_id: str
    summary: str
    created_at: datetime
    size_bytes: int
    status: str = PLAN_STATUS_ACTIVE


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter from plan text.

    Returns (metadata_dict, body).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        raw = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(raw, dict):
        return {}, text
    meta = {str(k): str(v) for k, v in raw.items()}
    return meta, text[m.end():]


def _build_frontmatter(
    session_id: str,
    summary: str,
    created_at: datetime,
    status: str = PLAN_STATUS_ACTIVE,
) -> str:
    """Build YAML frontmatter string."""
    meta = {
        "session_id": str(session_id),
        "summary": str(summary),
        "status": str(status),
        "created_at": created_at.isoformat(),
    }
    body = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{body}---\n"


def _plan_info_from_path(path: Path) -> PlanInfo | None:
    """Read a plan file and return PlanInfo, or None on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    plan_id = path.stem
    meta, body = _parse_frontmatter(text)
    session_id = meta.get("session_id", "")
    summary = meta.get("summary", "")
    status = meta.get("status", PLAN_STATUS_ACTIVE)
    if status not in (PLAN_STATUS_ACTIVE, PLAN_STATUS_COMPLETED, PLAN_STATUS_PENDING, PLAN_STATUS_CANCELLED):
        status = PLAN_STATUS_CANCELLED
    created_str = meta.get("created_at", "")

    created_at: datetime
    if created_str:
        try:
            created_at = datetime.fromisoformat(created_str)
        except ValueError:
            created_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    else:
        created_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    return PlanInfo(
        plan_id=plan_id,
        short_id=plan_id[:8],
        file_path=path,
        session_id=session_id,
        summary=summary,
        created_at=created_at,
        size_bytes=len(text.encode("utf-8")),
        status=status,
    )


def save_plan(
    config: "AppConfig",
    body: str,
    session_id: str,
    summary: str = "",
) -> str | None:
    """Save a plan to the project plans directory.

    Marks any existing *active* plans in the same session as *cancelled*.
    Returns the absolute file path, or None if body is empty.
    """
    if not body or not body.strip():
        return None

    plans_dir = config.project_plans_dir
    plans_dir.mkdir(parents=True, exist_ok=True)

    # Cancel previous active plans in the same session
    for path in plans_dir.glob("*.md"):
        info = _plan_info_from_path(path)
        if info and info.session_id == session_id and info.status == PLAN_STATUS_ACTIVE:
            _update_status_in_file(path, PLAN_STATUS_CANCELLED)

    plan_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    frontmatter = _build_frontmatter(session_id, summary, created_at)

    from hooty.concurrency import atomic_write_text

    plan_path = plans_dir / f"{plan_id}.md"
    atomic_write_text(plan_path, frontmatter + body)
    return str(plan_path)


def update_plan_status(config: "AppConfig", file_path: str, status: str) -> bool:
    """Update the status of a plan file. Returns True on success."""
    path = Path(file_path)
    if not path.exists():
        return False
    return _update_status_in_file(path, status)


def _update_status_in_file(path: Path, status: str) -> bool:
    """Rewrite frontmatter status in a plan file."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False

    m = _FRONTMATTER_RE.match(text)
    if not m:
        return False

    fm_body = m.group(1)
    # Replace or insert status line
    if re.search(r"^status:\s", fm_body, re.MULTILINE):
        new_fm = re.sub(r"^status:\s.*$", f"status: {status}", fm_body, flags=re.MULTILINE)
    else:
        new_fm = fm_body + f"\nstatus: {status}"

    from hooty.concurrency import atomic_write_text

    new_text = f"---\n{new_fm}\n---\n" + text[m.end():]
    try:
        atomic_write_text(path, new_text)
    except Exception:
        return False
    return True


def list_plans(config: "AppConfig") -> list[PlanInfo]:
    """List all plans, newest first."""
    plans_dir = config.project_plans_dir
    if not plans_dir.exists():
        return []

    plans: list[PlanInfo] = []
    for path in plans_dir.glob("*.md"):
        info = _plan_info_from_path(path)
        if info:
            plans.append(info)

    plans.sort(key=lambda p: p.created_at, reverse=True)
    return plans


def search_plans(config: "AppConfig", keyword: str) -> list[PlanInfo]:
    """Search plans by keyword (case-insensitive)."""
    kw_lower = keyword.lower()
    results: list[PlanInfo] = []

    plans_dir = config.project_plans_dir
    if not plans_dir.exists():
        return results

    for path in plans_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        if kw_lower in text:
            info = _plan_info_from_path(path)
            if info:
                results.append(info)

    results.sort(key=lambda p: p.created_at, reverse=True)
    return results


def get_plan(config: "AppConfig", id_prefix: str) -> PlanInfo | None:
    """Get a plan by ID prefix match."""
    plans_dir = config.project_plans_dir
    if not plans_dir.exists():
        return None

    prefix_lower = id_prefix.lower()
    for path in plans_dir.glob("*.md"):
        if path.stem.lower().startswith(prefix_lower):
            return _plan_info_from_path(path)
    return None


def get_plan_body(config: "AppConfig", id_prefix: str) -> tuple[PlanInfo | None, str]:
    """Get a plan's parsed body (without frontmatter) by ID prefix.

    Returns (PlanInfo, body_text) on success, or (None, "") if not found.
    """
    info = get_plan(config, id_prefix)
    if info is None:
        return None, ""
    try:
        text = info.file_path.read_text(encoding="utf-8")
    except Exception:
        return None, ""
    _meta, body = _parse_frontmatter(text)
    return info, body


def update_plan_body(
    config: "AppConfig",
    id_prefix: str,
    body: str,
    summary: str | None = None,
) -> bool:
    """Update an existing plan's body in-place (preserves plan_id, session_id, created_at).

    Optionally updates the summary. Returns True on success.
    """
    info = get_plan(config, id_prefix)
    if info is None:
        return False
    path = info.file_path
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False

    meta, _old_body = _parse_frontmatter(text)
    if not meta:
        return False

    # Update summary if provided
    if summary is not None:
        meta["summary"] = summary

    # Rebuild frontmatter from existing metadata
    fm_body = yaml.dump(
        {k: v for k, v in meta.items()},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    new_text = f"---\n{fm_body}---\n{body}"

    from hooty.concurrency import atomic_write_text

    try:
        atomic_write_text(path, new_text)
    except Exception:
        return False
    return True


def delete_plans(config: "AppConfig", plan_ids: list[str]) -> int:
    """Delete plans by ID. Returns number deleted."""
    plans_dir = config.project_plans_dir
    if not plans_dir.exists():
        return 0

    deleted = 0
    for plan_id in plan_ids:
        path = plans_dir / f"{plan_id}.md"
        if path.exists():
            path.unlink()
            deleted += 1
    return deleted


def format_plan_for_display(plan: PlanInfo) -> dict[str, str]:
    """Format a PlanInfo for display."""
    created = plan.created_at.strftime("%Y-%m-%d %H:%M")

    size = plan.size_bytes
    if size >= 1024 * 1024:
        size_str = f"{size / (1024 * 1024):.1f}MB"
    elif size >= 1024:
        size_str = f"{size / 1024:.1f}KB"
    else:
        size_str = f"{size}B"

    summary = plan.summary or "(no summary)"
    summary = truncate_display(summary, 50)

    status_icon = PLAN_STATUS_ICONS.get(plan.status, "?")

    return {
        "short_id": plan.short_id,
        "created_at": created,
        "size": size_str,
        "summary": summary,
        "status_icon": status_icon,
        "status": plan.status,
    }



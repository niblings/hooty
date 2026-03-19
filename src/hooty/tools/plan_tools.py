"""Plan management tools — LLM-callable CRUD for project plans."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agno.tools import Toolkit

if TYPE_CHECKING:
    from hooty.config import AppConfig

# Truncation threshold for plans_get body
_MAX_BODY_CHARS = 10_000

_VALID_STATUSES = {"active", "completed", "pending", "cancelled"}


class PlanTools(Toolkit):
    """Toolkit for reading and writing project plans.

    Available in both planning and coding modes. Provides plan CRUD
    so the LLM can inspect existing plans, create new ones, and
    iteratively refine plans before handing off to coding mode.
    """

    def __init__(
        self,
        config: "AppConfig",
        session_id_ref: list[str],
    ) -> None:
        self._config = config
        self._session_id_ref = session_id_ref
        super().__init__(
            name="plan_tools",
            instructions=(
                "Plan management tools for reading and writing project plans.\n"
                "- plans_list(status_filter): List existing plans. Check before creating new ones.\n"
                "- plans_get(plan_id): Read full plan content by short_id prefix.\n"
                "- plans_search(keyword): Find plans by keyword.\n"
                "- plans_create(body, summary): Save a new plan. Auto-cancels previous "
                "active plans in this session. Returns plan_id for later reference.\n"
                "- plans_update(plan_id, body, summary): Update existing plan in-place "
                "(keeps plan_id stable for iterative refinement).\n"
                "- plans_update_status(plan_id, status): Change status "
                "(active/completed/pending/cancelled).\n\n"
                "Status semantics:\n"
                "- active: Currently valid plan being worked on.\n"
                "- completed: Plan finalized and handed off to coding mode.\n"
                "- pending: Shelved — revisit later. Not auto-cancelled by new plans.\n"
                "- cancelled: Abandoned or replaced by a newer plan.\n\n"
                "In planning mode: Use plans_create -> plans_update cycle to build your plan, "
                "then pass plan_id to exit_plan_mode().\n"
                "In coding mode: Use plans_list/plans_get to reference existing plans."
            ),
            add_instructions=True,
        )
        self.register(self.plans_list)
        self.register(self.plans_get)
        self.register(self.plans_search)
        self.register(self.plans_create)
        self.register(self.plans_update)
        self.register(self.plans_update_status)

    def plans_list(self, status_filter: str = "") -> str:
        """List all plans, optionally filtered by status.

        :param status_filter: Filter by status (active/completed/pending/cancelled). Empty for all.
        :return: Formatted list of plans.
        """
        from hooty.plan_store import list_plans, format_plan_for_display

        plans = list_plans(self._config)

        if status_filter:
            sf = status_filter.strip().lower()
            if sf in _VALID_STATUSES:
                plans = [p for p in plans if p.status == sf]
            else:
                return f"Invalid status filter: {status_filter!r}. Valid: active, completed, pending, cancelled."

        if not plans:
            return "No plans found."

        lines = []
        for p in plans:
            info = format_plan_for_display(p)
            lines.append(
                f"{info['status_icon']} [{info['short_id']}] {info['created_at']}  "
                f"{info['status']:11s}  {info['size']:>6s}  {info['summary']}"
            )
        return "\n".join(lines)

    def plans_get(self, plan_id: str) -> str:
        """Read a plan's full content by ID prefix.

        :param plan_id: Plan ID or short_id prefix.
        :return: Plan content (truncated if >10k chars).
        """
        from hooty.plan_store import get_plan_body

        info, body = get_plan_body(self._config, plan_id)
        if info is None:
            return f"Plan not found: {plan_id!r}"

        header = (
            f"Plan: {info.short_id} ({info.plan_id})\n"
            f"Status: {info.status}\n"
            f"Summary: {info.summary or '(none)'}\n"
            f"Created: {info.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"Session: {info.session_id[:8] if info.session_id else '(none)'}\n"
            f"---\n"
        )

        if len(body) > _MAX_BODY_CHARS:
            truncated = body[:_MAX_BODY_CHARS]
            return (
                header + truncated + "\n\n"
                f"[TRUNCATED — {len(body)} chars total. "
                f"Use read_file('{info.file_path}') for full content.]"
            )
        return header + body

    def plans_search(self, keyword: str) -> str:
        """Search plans by keyword (case-insensitive).

        :param keyword: Keyword to search for.
        :return: Matching plans.
        """
        from hooty.plan_store import search_plans, format_plan_for_display

        if not keyword.strip():
            return "Keyword cannot be empty."

        results = search_plans(self._config, keyword)
        if not results:
            return f"No plans matching: {keyword!r}"

        lines = []
        for p in results:
            info = format_plan_for_display(p)
            lines.append(
                f"{info['status_icon']} [{info['short_id']}] {info['created_at']}  "
                f"{info['status']:11s}  {info['summary']}"
            )
        return "\n".join(lines)

    def plans_create(self, body: str, summary: str = "") -> str:
        """Create a new plan. Auto-cancels previous active plans in this session.

        :param body: Plan content (markdown).
        :param summary: Brief summary of the plan.
        :return: Plan ID on success, error message on failure.
        """
        from hooty.plan_store import save_plan

        if not body or not body.strip():
            return "Error: Plan body cannot be empty."

        session_id = self._session_id_ref[0]
        file_path = save_plan(
            self._config, body=body, session_id=session_id, summary=summary,
        )
        if file_path is None:
            return "Error: Failed to save plan."

        # Extract plan_id from the file path
        from pathlib import Path

        plan_id = Path(file_path).stem
        short_id = plan_id[:8]
        return f"Plan created: {short_id} (full ID: {plan_id})"

    def plans_update(self, plan_id: str, body: str, summary: str = "") -> str:
        """Update an existing plan's body in-place (keeps plan_id stable).

        :param plan_id: Plan ID or short_id prefix.
        :param body: New plan content (markdown).
        :param summary: Updated summary (empty to keep existing).
        :return: Confirmation or error message.
        """
        from hooty.plan_store import update_plan_body

        if not body or not body.strip():
            return "Error: Plan body cannot be empty."

        # Pass None for summary if empty string (keep existing)
        new_summary = summary if summary else None
        ok = update_plan_body(self._config, plan_id, body, summary=new_summary)
        if not ok:
            return f"Error: Plan not found or update failed: {plan_id!r}"
        return f"Plan updated: {plan_id}"

    def plans_update_status(self, plan_id: str, status: str) -> str:
        """Change a plan's status.

        :param plan_id: Plan ID or short_id prefix.
        :param status: New status (active/completed/pending/cancelled).
        :return: Confirmation or error message.
        """
        from hooty.plan_store import get_plan, update_plan_status

        status_lower = status.strip().lower()
        if status_lower not in _VALID_STATUSES:
            return f"Invalid status: {status!r}. Valid: active, completed, pending, cancelled."

        info = get_plan(self._config, plan_id)
        if info is None:
            return f"Plan not found: {plan_id!r}"

        ok = update_plan_status(self._config, str(info.file_path), status_lower)
        if not ok:
            return f"Error: Failed to update status for plan {plan_id!r}."
        return f"Plan {info.short_id} status changed to: {status_lower}"

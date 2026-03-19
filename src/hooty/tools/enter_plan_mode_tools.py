"""Enter plan mode tool for coding-to-planning mode transition."""

from __future__ import annotations

from agno.tools import Toolkit


class EnterPlanModeTools(Toolkit):
    """Toolkit providing enter_plan_mode() for coding mode.

    When the agent determines that planning is needed, it calls
    enter_plan_mode() with a reason. The REPL detects the flag and
    presents a UI for the user to choose how to proceed (revise
    current plan, start new plan, or continue coding).
    """

    def __init__(
        self,
        enter_plan_ref: list[bool],
        pending_reason_ref: list[str | None],
        pending_revise_ref: list[bool],
    ) -> None:
        self._enter_plan_ref = enter_plan_ref
        self._pending_reason_ref = pending_reason_ref
        self._pending_revise_ref = pending_revise_ref
        super().__init__(
            name="enter_plan_mode_tools",
            instructions=(
                "Call enter_plan_mode() when: "
                "(1) the user explicitly requests planning, "
                "(2) the task is complex/large-scale and needs alignment, or "
                "(3) requirements are ambiguous with multiple viable approaches. "
                "Use plans_list() first to check existing plans and their status. "
                "This helps you decide revise=True vs revise=False accurately. "
                "Set revise=True to revise the current plan, "
                "revise=False for a new plan. "
                "Do NOT use for minor issues — stay in coding mode."
            ),
            add_instructions=True,
        )
        self.register(self.enter_plan_mode)

    def enter_plan_mode(self, reason: str, revise: bool = False) -> str:
        """Propose switching to planning mode.

        :param reason: Why planning is needed.
        :param revise: True if revising the current plan, False for a new plan.
        :return: Acknowledgement message.
        """
        self._enter_plan_ref[0] = True
        self._pending_reason_ref[0] = reason
        self._pending_revise_ref[0] = revise
        return (
            "System will present planning options after this response. "
            "IMPORTANT: Do NOT call any more tools. End your response now."
        )

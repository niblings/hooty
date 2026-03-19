"""Exit plan mode tool for planning-to-coding mode transition."""

from __future__ import annotations

from agno.tools import Toolkit


class ExitPlanModeTools(Toolkit):
    """Toolkit providing exit_plan_mode() for planning mode.

    When the agent's plan is complete, it calls exit_plan_mode() with a
    summary. The shared *auto_execute_ref* flag is set so the REPL can
    present the mode-switch confirmation and transition to coding mode.
    The plan summary is stored in *pending_plan_ref* for the auto-execute
    message.
    """

    def __init__(
        self,
        auto_execute_ref: list[bool],
        pending_plan_ref: list[str | None],
        pending_plan_id_ref: list[str | None] | None = None,
    ) -> None:
        self._auto_execute_ref = auto_execute_ref
        self._pending_plan_ref = pending_plan_ref
        self._pending_plan_id_ref = pending_plan_id_ref
        super().__init__(
            name="exit_plan_mode_tools",
            instructions=(
                "When your plan is complete, call exit_plan_mode() "
                "to propose switching to coding mode. "
                "If you saved the plan via plans_create/plans_update, "
                "pass its plan_id so the coding agent receives the correct file. "
                "Without plan_id, your last response text is saved as the plan."
            ),
            add_instructions=True,
        )
        self.register(self.exit_plan_mode)

    def exit_plan_mode(self, plan_summary: str, plan_id: str = "") -> str:
        """Propose transitioning to coding mode to implement the plan.

        :param plan_summary: A brief summary of the plan to execute.
        :param plan_id: Optional plan ID from plans_create/plans_update. If provided,
            the coding agent receives that plan file directly instead of the last response.
        :return: Acknowledgement message.
        """
        self._auto_execute_ref[0] = True
        self._pending_plan_ref[0] = plan_summary
        if self._pending_plan_id_ref is not None:
            self._pending_plan_id_ref[0] = plan_id or None
        return (
            "System will present the mode-switch confirmation after this response. "
            "IMPORTANT: Do NOT call any more tools. End your response now."
        )

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from agent.executor import ExecutorOutput, StepExecutor, ToolSpec
from orchestration.messages import CoderMessage
from orchestration.task_state import TaskState
from utils.logging import get_logger

logger = get_logger("agent.coder")


class CoderAgent:
    """
    Executes the plan in TaskState and produces file changes.

    On the first iteration it runs the plan as-is. On subsequent iterations it
    injects reviewer / tester feedback into the executor's memory context so the
    LLM can address the problems that caused the previous rejection.
    """

    def __init__(self, llm: BaseChatModel, tools: list[ToolSpec]) -> None:
        self.executor = StepExecutor(llm=llm, tools=tools)
        logger.info("CoderAgent initialized", extra={"event": "coder_init"})

    def code(self, state: TaskState) -> CoderMessage:
        """Execute the plan stored in *state* and return a CoderMessage."""
        if state.plan is None:
            logger.warning(
                "CoderAgent called with no plan in TaskState",
                extra={"event": "coder_no_plan", "session_id": state.session_id},
            )
            return CoderMessage(success=False, error="No plan available to execute.")

        logger.info(
            "CoderAgent starting execution",
            extra={
                "event": "coder_start",
                "session_id": state.session_id,
                "iteration": state.iteration,
                "plan_steps": len(state.plan.steps),
            },
        )

        # On retry iterations: inject prior feedback so the LLM can correct itself.
        if state.iteration > 1:
            feedback_parts: list[str] = []
            if state.review_feedback:
                feedback_parts.append(f"Reviewer feedback: {state.review_feedback}")
            if state.test_feedback:
                feedback_parts.append(f"Tester feedback: {state.test_feedback}")
            if feedback_parts:
                self.executor.memory_context = [HumanMessage(content="\n".join(feedback_parts))]

        output: ExecutorOutput = self.executor.execute(state.plan, session_id=state.session_id)

        changed_files = [c.filename for c in output.all_file_changes]
        state.log_decision(
            agent="coder",
            action="execute_plan",
            outcome=f"{len(output.all_file_changes)} file(s) changed",
            details={"iteration": state.iteration, "files": changed_files},
        )

        logger.info(
            "CoderAgent completed",
            extra={
                "event": "coder_complete",
                "file_changes": len(output.all_file_changes),
                "iteration": state.iteration,
            },
        )

        return CoderMessage(
            file_changes=output.all_file_changes,
            success=bool(output.all_file_changes),
            notes=(f"Iteration {state.iteration}: {len(output.all_file_changes)} file(s) changed."),
        )

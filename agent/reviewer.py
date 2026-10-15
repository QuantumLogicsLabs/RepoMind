from __future__ import annotations

from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from orchestration.messages import ReviewerMessage
from orchestration.task_state import TaskState
from utils.logging import get_logger

logger = get_logger("agent.reviewer")

_PREVIEW_CHARS = 600


class ReviewDecision(BaseModel):
    """Structured output from the reviewer LLM."""

    approved: bool = Field(
        ..., description="True if the changes correctly implement the instruction."
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Specific problems found. Empty when approved.",
    )
    feedback: str = Field(
        default="",
        description="Actionable guidance for the Coder to address on the next iteration.",
    )


class ReviewerAgent:
    """
    Reviews generated file changes against the original instruction and plan.

    Can reject with actionable feedback, which causes the Orchestrator to loop
    back to the CoderAgent for a corrected attempt.
    """

    _SYSTEM = (
        "You are a senior code reviewer for the RepoMind AI system.\n"
        "You will receive:\n"
        "  1. The original user instruction.\n"
        "  2. The ordered plan steps.\n"
        "  3. A preview of the file changes produced by the Coder agent.\n\n"
        "REVIEW CRITERIA:\n"
        "- Do the changes implement what the instruction asked for?\n"
        "- Is the Python syntax valid (no bare '...', no '# TODO' stubs)?\n"
        "- Are there obvious logic errors or missing edge-case handling?\n"
        "- Does each change match its corresponding plan step?\n"
        "- Are all new imports present at the top of the file?\n\n"
        "Set approved=True only when the changes look correct and complete.\n"
        "Set approved=False and list concrete, actionable issues otherwise.\n"
        "Be strict but fair — reject only for real implementation problems."
    )

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self._SYSTEM),
                (
                    "human",
                    (
                        "Instruction:\n{instruction}\n\n"
                        "Plan steps:\n{plan_steps}\n\n"
                        "File changes (preview):\n{file_changes}\n\n"
                        "Return your review decision."
                    ),
                ),
            ]
        )
        logger.info("ReviewerAgent initialized", extra={"event": "reviewer_init"})

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_plan(state: TaskState) -> str:
        if not state.plan:
            return "(no plan)"
        return "\n".join(f"Step {s.id}: {s.task}  →  {s.target_function}" for s in state.plan.steps)

    @staticmethod
    def _format_changes(state: TaskState) -> str:
        if not state.file_changes:
            return "(no changes)"
        parts: list[str] = []
        for c in state.file_changes:
            preview = c.updated_content[:_PREVIEW_CHARS]
            if len(c.updated_content) > _PREVIEW_CHARS:
                preview += "\n... (truncated)"
            parts.append(f"File: {c.filename}\nReason: {c.reason}\nPreview:\n{preview}")
        return "\n\n---\n\n".join(parts)

    def _invoke_chain(self, inputs: dict) -> ReviewDecision:
        """Build and invoke the LLM chain. Extracted for testability."""
        chain = self.prompt | self.llm.with_structured_output(ReviewDecision)
        return cast(ReviewDecision, chain.invoke(inputs))

    # ── public API ────────────────────────────────────────────────────────────

    def review(self, state: TaskState) -> ReviewerMessage:
        """Review the file changes stored in *state* and return a ReviewerMessage."""
        logger.info(
            "ReviewerAgent starting review",
            extra={
                "event": "reviewer_start",
                "session_id": state.session_id,
                "iteration": state.iteration,
            },
        )

        decision: ReviewDecision = self._invoke_chain(
            {
                "instruction": state.instruction,
                "plan_steps": self._format_plan(state),
                "file_changes": self._format_changes(state),
            }
        )

        outcome = "approved" if decision.approved else "rejected"
        state.log_decision(
            agent="reviewer",
            action="review_changes",
            outcome=outcome,
            details={"issues": decision.issues, "iteration": state.iteration},
        )

        logger.info(
            "ReviewerAgent completed",
            extra={
                "event": "reviewer_complete",
                "approved": decision.approved,
                "issues_count": len(decision.issues),
                "iteration": state.iteration,
            },
        )

        return ReviewerMessage(
            approved=decision.approved,
            issues=decision.issues,
            feedback=decision.feedback,
        )

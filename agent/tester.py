from __future__ import annotations

from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from orchestration.messages import TesterMessage
from orchestration.task_state import TaskState
from utils.logging import get_logger

logger = get_logger("agent.tester")

_PREVIEW_CHARS = 600


class TestDecision(BaseModel):
    """Structured output from the tester LLM."""

    passed: bool = Field(
        ...,
        description="True if ALL plan step acceptance criteria appear to be satisfied.",
    )
    failures: list[str] = Field(
        default_factory=list,
        description="Acceptance criteria that are not yet met. Empty when passed.",
    )
    feedback: str = Field(
        default="",
        description="Specific guidance for the Coder to make the changes pass.",
    )


class TesterAgent:
    """
    Validates that the file changes satisfy every plan step's acceptance criteria.

    Can request revisions by returning passed=False with specific failures and
    actionable feedback for the CoderAgent to address on the next iteration.
    """

    _SYSTEM = (
        "You are a senior QA engineer for the RepoMind AI system.\n"
        "You will receive:\n"
        "  1. The original user instruction.\n"
        "  2. Each plan step together with its acceptance_criteria.\n"
        "  3. A preview of the file changes produced by the Coder agent.\n\n"
        "YOUR JOB:\n"
        "For every plan step, check whether its acceptance_criteria is satisfied by\n"
        "the corresponding file changes.\n\n"
        "PASS ONLY IF:\n"
        "- Every acceptance criterion is clearly met in the code.\n"
        "- There are no obvious missing test cases or unhandled edge cases.\n"
        "- The implementation is complete enough to be merged.\n\n"
        "Return passed=False and list specific failures with actionable feedback\n"
        "whenever one or more criteria are not satisfied."
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
                        "Plan steps with acceptance criteria:\n{plan_steps}\n\n"
                        "File changes (preview):\n{file_changes}\n\n"
                        "Evaluate whether every acceptance criterion is satisfied."
                    ),
                ),
            ]
        )
        logger.info("TesterAgent initialized", extra={"event": "tester_init"})

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_plan(state: TaskState) -> str:
        if not state.plan:
            return "(no plan)"
        return "\n".join(
            f"Step {s.id}: {s.task}\n  acceptance_criteria: {s.acceptance_criteria}"
            for s in state.plan.steps
        )

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

    def _invoke_chain(self, inputs: dict) -> TestDecision:
        """Build and invoke the LLM chain. Extracted for testability."""
        chain = self.prompt | self.llm.with_structured_output(TestDecision)
        return cast(TestDecision, chain.invoke(inputs))

    # ── public API ────────────────────────────────────────────────────────────

    def test(self, state: TaskState) -> TesterMessage:
        """Evaluate file changes in *state* against plan acceptance criteria."""
        logger.info(
            "TesterAgent starting evaluation",
            extra={
                "event": "tester_start",
                "session_id": state.session_id,
                "iteration": state.iteration,
            },
        )

        decision: TestDecision = self._invoke_chain(
            {
                "instruction": state.instruction,
                "plan_steps": self._format_plan(state),
                "file_changes": self._format_changes(state),
            }
        )

        outcome = "passed" if decision.passed else "failed"
        state.log_decision(
            agent="tester",
            action="evaluate_changes",
            outcome=outcome,
            details={"failures": decision.failures, "iteration": state.iteration},
        )

        logger.info(
            "TesterAgent completed",
            extra={
                "event": "tester_complete",
                "passed": decision.passed,
                "failures_count": len(decision.failures),
                "iteration": state.iteration,
            },
        )

        return TesterMessage(
            passed=decision.passed,
            failures=decision.failures,
            feedback=decision.feedback,
        )

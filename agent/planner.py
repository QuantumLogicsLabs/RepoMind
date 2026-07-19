from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_core.language_models.chat_models import BaseChatModel

from tools.code_parser import summarize_project_map

MAX_PLAN_STEPS = 10


class PlanStep(BaseModel):
    id: int = Field(..., description="1-based sequence number.")
    task: str = Field(..., description="Single actionable edit task.")
    target_files: List[str] = Field(
        default_factory=list,
        description=(
            "Exact relative file paths to edit, e.g. ['agent/executor.py']. "
            "Must reference real files, not vague module names."
        ),
    )
    target_function: str = Field(
        ...,
        description=(
            "The exact function or class name to create or modify, e.g. 'StepExecutor.execute'. "
            "Use '<new>' if the step creates a brand-new function."
        ),
    )
    new_logic: str = Field(
        ...,
        description=(
            "Precise description of the new logic to implement inside target_function. "
            "Include parameter changes, return-value changes, and any new imports needed. "
            "Do NOT use vague phrases like 'improve this' or 'fix the bug'."
        ),
    )
    expected_output: str = Field(
        ...,
        description=(
            "Concrete, observable result when this step is done correctly. "
            "E.g. 'execute() retries a step once when file_changes is empty, then continues.' "
            "Avoid vague criteria like 'works correctly'."
        ),
    )
    acceptance_criteria: str = Field(
        ...,
        description=(
            "How a reviewer can verify this step is done: a unit test assertion, "
            "a log message, or an explicit runtime behaviour."
        ),
    )


class Plan(BaseModel):
    steps: List[PlanStep] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def cap_steps(cls, steps: List[PlanStep]) -> List[PlanStep]:
        """Hard cap: never more than MAX_PLAN_STEPS steps to prevent infinite loops."""
        if len(steps) > MAX_PLAN_STEPS:
            steps = steps[:MAX_PLAN_STEPS]
        return steps


class TaskPlanner:
    """
    Turns a user instruction into an ordered, concrete set of code-edit steps.

    Each step names the exact file, the exact function, the new logic to write,
    and the expected observable output — so the executor never has to guess.
    """

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are a senior software engineer acting as a code-edit planner for the RepoMind AI agent.\n"
                        "\n"
                        "Your job is to decompose the user's instruction into an ordered list of CONCRETE implementation steps.\n"
                        "Each step will be executed independently by a code-generation LLM that has NO memory of previous steps.\n"
                        "Therefore every step must be 100 % self-contained and unambiguous.\n"
                        "\n"
                        "STRICT RULES:\n"
                        "1. MAXIMUM {max_steps} steps. If the task needs more, find the minimal subset that achieves the goal.\n"
                        "2. Every step MUST specify:\n"
                        "   - target_files: exact file path(s) relative to the repo root, e.g. 'agent/executor.py'\n"
                        "   - target_function: the exact function or class.method name to touch, e.g. 'StepExecutor.execute'\n"
                        "   - new_logic: a precise, line-level description of what code to add/change/remove inside that function\n"
                        "   - expected_output: a concrete observable result (not 'it works')\n"
                        "   - acceptance_criteria: how a test or reviewer can confirm the step is done\n"
                        "3. Prioritize repository intelligence from the project map: README.md, ARCHITECTURE.md, framework configs, dependency files, and entry points should be preferred over arbitrary source files when relevant.\n"
                        "4. NEVER produce vague steps like 'improve the prompt' or 'fix the bug'.\n"
                        "5. NEVER reference a file or function that doesn't exist in the repo without also creating it first.\n"
                        "6. Steps must be ordered: if step B depends on step A, A must come first.\n"
                        "7. Each step edits ONE logical unit (one function or one class). Split larger changes across multiple steps.\n"
                        "\n"
                        "BAD step (reject this pattern):\n"
                        "  task: 'Improve the executor'\n"
                        "  target_files: ['agent/']\n"
                        "  new_logic: 'Make it better'\n"
                        "\n"
                        "GOOD step (follow this pattern):\n"
                        "  task: 'Add retry logic to StepExecutor.execute when file_changes is empty'\n"
                        "  target_files: ['agent/executor.py']\n"
                        "  target_function: 'StepExecutor.execute'\n"
                        '  new_logic: \'After tool.fn() returns payload, check if payload["file_changes"] is empty. '
                        "If so, call tool.fn(decision.tool_input) a second time. Use the second result regardless.'\n"
                        "  expected_output: 'execute() calls the tool twice when the first call returns no file_changes'\n"
                        "  acceptance_criteria: 'Unit test patches tool.fn to return empty first, non-empty second; "
                        "asserts all_file_changes is non-empty'\n"
                    ),
                ),
                (
                    "human",
                    (
                        "Conversation context (most recent {max_context_msgs} messages):\n{context}\n\n"
                        "Repository intelligence:\n{project_map}\n\n"
                        "User instruction:\n{instruction}\n\n"
                        "Return a plan with 1-based step ids. Maximum {max_steps} steps."
                    ),
                ),
            ]
        )

    def _context_to_text(self, context_messages: list) -> str:
        """Serialize LangChain messages to readable text for the prompt."""
        if not context_messages:
            return "(no prior context)"
        lines = []
        for msg in context_messages:
            role = msg.type.upper()
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    def _project_map_to_text(self, project_map: Optional[dict[str, Any]]) -> str:
        """Serialize the structured project map for the planner prompt."""
        if not project_map:
            return "(no project map available)"
        return summarize_project_map(project_map)

    def build_chain(self) -> Runnable:
        """Return the LangChain runnable for planning."""
        return self.prompt | self.llm.with_structured_output(Plan)

    def plan(
        self,
        instruction: str,
        context_messages: list,
        project_map: Optional[dict[str, Any]] = None,
    ) -> Plan:
        """
        Produce a Plan from the user's instruction and session context.

        Args:
            instruction: The user's plain-English change request.
            context_messages: LangChain BaseMessage list from MemoryManager.

        Returns:
            A Plan with at most MAX_PLAN_STEPS steps, each fully specified.
        """
        chain = self.build_chain()
        return chain.invoke(
            {
                "instruction": instruction,
                "context": self._context_to_text(context_messages),
                "project_map": self._project_map_to_text(project_map),
                "max_steps": MAX_PLAN_STEPS,
                "max_context_msgs": 12,
            }
        )

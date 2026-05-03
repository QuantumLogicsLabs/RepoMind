from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_core.language_models.chat_models import BaseChatModel


class PlanStep(BaseModel):
    id: int = Field(..., description="1-based sequence number.")
    task: str = Field(..., description="Single actionable edit task.")
    target_files: List[str] = Field(default_factory=list, description="Likely files to edit.")
    acceptance_criteria: str = Field(..., description="How to verify this step is done.")


class Plan(BaseModel):
    steps: List[PlanStep] = Field(default_factory=list)


class TaskPlanner:
    """
    Turns user instruction into ordered code-edit steps.
    """

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are a senior software planning assistant. "
                        "Break the request into an ordered, minimal set of implementation steps. "
                        "Each step must be concrete and executable by a code-editing agent."
                    ),
                ),
                (
                    "human",
                    (
                        "Conversation context:\n{context}\n\n"
                        "New user instruction:\n{instruction}\n\n"
                        "Return a plan with 1-based step ids."
                    ),
                ),
            ]
        )

    def _context_to_text(self, context_messages) -> str:
        if not context_messages:
            return "(no prior context)"
        lines = []
        for msg in context_messages:
            role = msg.type.upper()
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    def build_chain(self) -> Runnable:
        return self.prompt | self.llm.with_structured_output(Plan)

    def plan(self, instruction: str, context_messages) -> Plan:
        chain = self.build_chain()
        return chain.invoke(
            {
                "instruction": instruction,
                "context": self._context_to_text(context_messages),
            }
        )
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel

from agent.planner import Plan, PlanStep


ToolFn = Callable[[Dict[str, Any]], Dict[str, Any]]


class FileChange(BaseModel):
    filename: str
    updated_content: str
    reason: str = Field(default="", description="Why this file was changed.")


class StepExecutionResult(BaseModel):
    step_id: int
    step_task: str
    tool_name: Optional[str] = None
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    file_changes: List[FileChange] = Field(default_factory=list)
    notes: str = ""


class ExecutorOutput(BaseModel):
    results: List[StepExecutionResult] = Field(default_factory=list)
    all_file_changes: List[FileChange] = Field(default_factory=list)


class ToolDecision(BaseModel):
    tool_name: str = Field(..., description="Which tool to call.")
    tool_input: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the selected tool.")


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: ToolFn


class StepExecutor:
    """
    Executes plan steps one-by-one and returns structured file changes.
    Each tool returns dict payload; expected optional key: `file_changes`.
    """

    def __init__(self, llm: BaseChatModel, tools: List[ToolSpec]) -> None:
        self.llm = llm
        self.tools_by_name = {t.name: t for t in tools}

        tool_descriptions = "\n".join([f"- {t.name}: {t.description}" for t in tools]) or "- noop: do nothing"

        self.tool_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are a code execution planner. Choose exactly one tool for the current step.\n"
                        "Return only structured data."
                    ),
                ),
                (
                    "human",
                    (
                        "Available tools:\n{tool_descriptions}\n\n"
                        "Current step:\n{step}\n\n"
                        "Previous execution summary:\n{previous_summary}\n\n"
                        "Choose the best tool and arguments."
                    ),
                ),
            ]
        )

        self.tool_descriptions = tool_descriptions

    def _decide_tool(self, step: PlanStep, previous_summary: str) -> ToolDecision:
        chain = self.tool_prompt | self.llm.with_structured_output(ToolDecision)
        return chain.invoke(
            {
                "tool_descriptions": self.tool_descriptions,
                "step": json.dumps(step.model_dump(), indent=2),
                "previous_summary": previous_summary or "(none)",
            }
        )

    def execute(self, plan: Plan) -> ExecutorOutput:
        results: List[StepExecutionResult] = []
        all_changes: List[FileChange] = []

        for step in plan.steps:
            previous_summary = "\n".join([f"{r.step_id}: {r.notes}" for r in results])
            decision = self._decide_tool(step, previous_summary)

            step_result = StepExecutionResult(
                step_id=step.id,
                step_task=step.task,
                tool_name=decision.tool_name,
                tool_input=decision.tool_input,
            )

            tool = self.tools_by_name.get(decision.tool_name)
            if tool is None:
                step_result.notes = f"Tool '{decision.tool_name}' not found; step skipped."
                results.append(step_result)
                continue

            payload = tool.fn(decision.tool_input) or {}
            raw_changes = payload.get("file_changes", [])

            for c in raw_changes:
                change = FileChange(
                    filename=c["filename"],
                    updated_content=c["updated_content"],
                    reason=c.get("reason", f"Updated by step {step.id}"),
                )
                step_result.file_changes.append(change)
                all_changes.append(change)

            step_result.notes = payload.get("notes", "Executed successfully.")
            results.append(step_result)

        return ExecutorOutput(results=results, all_file_changes=all_changes)
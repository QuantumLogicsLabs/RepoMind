from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from langchain_core.language_models.chat_models import BaseChatModel

from agent.memory import MemoryManager
from agent.planner import TaskPlanner, Plan
from agent.executor import StepExecutor, ExecutorOutput, ToolSpec, FileChange


@dataclass
class ChainResult:
    session_id: str
    instruction: str
    plan: Plan
    execution: ExecutorOutput


class AgentChain:
    """
    Main LangChain-based orchestration:
    1) Read context from memory
    2) Build plan from instruction
    3) Execute each step with tools
    4) Persist outcomes back to memory
    """

    def __init__(self, llm: BaseChatModel, tools: List[ToolSpec], memory: MemoryManager | None = None) -> None:
        self.llm = llm
        self.memory = memory or MemoryManager()
        self.planner = TaskPlanner(llm=llm)
        self.executor = StepExecutor(llm=llm, tools=tools)

    def run(self, session_id: str, instruction: str) -> ChainResult:
        self.memory.append_user_message(session_id, instruction)
        context = self.memory.get_context_messages(session_id)

        plan = self.planner.plan(instruction=instruction, context_messages=context)
        self.memory.set_plan(session_id, [s.task for s in plan.steps])

        execution = self.executor.execute(plan)

        for result in execution.results:
            self.memory.mark_step_completed(session_id, result.step_task)

        summary = self._build_summary(plan, execution)
        self.memory.append_ai_message(session_id, summary)

        return ChainResult(
            session_id=session_id,
            instruction=instruction,
            plan=plan,
            execution=execution,
        )

    def _build_summary(self, plan: Plan, execution: ExecutorOutput) -> str:
        lines = [f"Planned {len(plan.steps)} step(s). Executed {len(execution.results)} step(s)."]
        if execution.all_file_changes:
            lines.append("File changes:")
            for c in execution.all_file_changes:
                lines.append(f"- {c.filename}: {c.reason}")
        else:
            lines.append("No file changes generated.")
        return "\n".join(lines)
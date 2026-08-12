from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from agent.executor import ExecutorOutput, StepExecutor, ToolSpec
from agent.memory import MemoryManager
from agent.planner import Plan, TaskPlanner
from prompts.system_prompt import SYSTEM_PROMPT
from tools.code_parser import analyze_plan_impact
from utils.logging import get_logger
from utils.metrics import metrics_collector

logger = get_logger("agent.chain")


@dataclass
class ChainResult:
    session_id: str
    instruction: str
    plan: Plan
    execution: ExecutorOutput
    impact_report: dict[str, Any]


class AgentChain:
    """
    Main LangChain-based orchestration:

    1. Inject the RepoMind system prompt as the first message in every run.
    2. Read context from memory (last 12 messages).
    3. Build a concrete plan from the instruction + memory context.
    4. Execute each step with tools, passing memory context to the executor.
    5. Persist outcomes back to memory.

    The system prompt (from prompts/system_prompt.py) is prepended to the
    context_messages list before being forwarded to both the planner and the
    executor, so every LLM call in the chain shares the same persona and rules.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[ToolSpec],
        memory: MemoryManager | None = None,
    ) -> None:
        self.llm = llm
        self.memory = memory or MemoryManager()
        self.planner = TaskPlanner(llm=llm)
        self.executor = StepExecutor(llm=llm, tools=tools)

        # Build the system message once — it never changes between runs.
        self._system_message = SystemMessage(content=SYSTEM_PROMPT)

    # ── Public API ───────────────────────────────────────────────────────────

    def run(self, session_id: str, instruction: str) -> ChainResult:
        """
        Execute one full agent turn: plan → execute → persist → summarise.

        Args:
            session_id: Unique identifier for this job / conversation session.
            instruction: The user's plain-English change request.

        Returns:
            ChainResult containing the session id, original instruction,
            the generated Plan, and the full ExecutorOutput.
        """
        return self.run_with_project_map(session_id=session_id, instruction=instruction)

    def run_with_project_map(
        self,
        session_id: str,
        instruction: str,
        project_map: dict[str, Any] | None = None,
    ) -> ChainResult:
        """Execute one full agent turn while supplying structured repository intelligence."""
        chain_start_time = time.perf_counter()
        logger.info(
            "Starting agent chain run",
            extra={
                "event": "chain_start",
                "session_id": session_id,
                "instruction": instruction,
            },
        )
        self.memory.append_user_message(session_id, instruction)

        raw_context = self.memory.get_context_messages(session_id)
        context_with_system = self._build_context(raw_context)

        plan = self.planner.plan(
            instruction=instruction,
            context_messages=context_with_system,
            project_map=project_map,
        )
        files_by_path = (project_map or {}).get("files", {})
        impact_report = analyze_plan_impact(plan.steps, files_by_path)
        self.memory.set_plan(session_id, [s.task for s in plan.steps])

        self._inject_memory_context(context_with_system)
        execution = self.executor.execute(plan)

        for result in execution.results:
            self.memory.mark_step_completed(session_id, result.step_task)

        summary = self._build_summary(plan, execution)
        self.memory.append_ai_message(session_id, summary)

        chain_duration_sec = time.perf_counter() - chain_start_time
        metrics_collector.record_duration("chain_duration_seconds", chain_duration_sec)

        logger.info(
            "Agent chain run completed",
            extra={
                "event": "chain_complete",
                "session_id": session_id,
                "planned_steps": len(plan.steps),
                "executed_steps": len(execution.results),
                "total_file_changes": len(execution.all_file_changes),
                "duration_ms": round(chain_duration_sec * 1000, 2),
            },
        )

        return ChainResult(
            session_id=session_id,
            instruction=instruction,
            plan=plan,
            execution=execution,
            impact_report=impact_report,
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _build_context(self, raw_context: list) -> list:
        """
        Prepend the RepoMind system message to the conversation history.

        The system message is always first so every LLM call — whether it
        comes from the planner or the executor — opens with the correct persona.
        """
        return [self._system_message] + list(raw_context)

    def _inject_memory_context(self, context_with_system: list) -> None:
        """
        Store the enriched context on the executor so its tool-selection and
        code-generation prompts can reference conversation history.

        StepExecutor.memory_context is read by _decide_tool when building
        the 'previous_summary' variable.  If a future refactor adds an
        explicit memory_context parameter to _decide_tool, remove this method.
        """
        self.executor.memory_context = context_with_system
        self.memory_context: list = []

    def _build_summary(self, plan: Plan, execution: ExecutorOutput) -> str:
        """
        Produce a concise human-readable summary of what the agent did.

        This summary is stored as an AI message in memory so follow-up
        refinement runs have full context of what was already changed.
        """
        retried_steps = [r.step_id for r in execution.results if r.retried]

        lines = [
    (
        f"Planned {len(plan.steps)} step(s). "
        f"Executed {len(execution.results)} step(s)."
    )
]

        if retried_steps:
            lines.append(f"Steps that required a retry due to empty file_changes: {retried_steps}")

        if execution.all_file_changes:
            lines.append(f"File changes ({len(execution.all_file_changes)} total):")
            for c in execution.all_file_changes:
                lines.append(f"  - {c.filename}: {c.reason}")
        else:
            lines.append("No file changes were generated.")

        skipped = [r for r in execution.results if not r.file_changes and r.tool_name is not None]
        if skipped:
            lines.append(
                "Steps that produced no output (tool not found or empty after retry): "
                + ", ".join(str(r.step_id) for r in skipped)
            )

        return "\n".join(lines)

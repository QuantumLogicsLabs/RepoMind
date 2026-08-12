from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
 task-10-persistent-jobs
from typing import Any, cast

from typing import Any
 main

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from agent.planner import Plan, PlanStep
from utils.logging import get_logger
from utils.metrics import metrics_collector

logger = get_logger("agent.executor")

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


class FileChange(BaseModel):
    filename: str = Field(
        ..., description="Relative path of the file being changed, e.g. 'agent/executor.py'."
    )
    updated_content: str = Field(
        ...,
        description=(
            "The COMPLETE new content of the file after the change. "
            "This must be the entire file — not a diff, not a snippet, not pseudocode. "
            "Copy unchanged sections verbatim and insert the new code in the correct location."
        ),
    )
    reason: str = Field(
        default="", description="One-sentence explanation of why this file was changed."
    )


class StepExecutionResult(BaseModel):
    step_id: int
    step_task: str
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    file_changes: list[FileChange] = Field(default_factory=list)
    notes: str = ""
    retried: bool = Field(
        default=False, description="True if this step was retried due to empty file_changes."
    )


class ExecutorOutput(BaseModel):
    results: list[StepExecutionResult] = Field(default_factory=list)
    all_file_changes: list[FileChange] = Field(default_factory=list)


class ToolDecision(BaseModel):
    tool_name: str = Field(..., description="Which tool to call.")
    tool_input: dict[str, Any] = Field(
        default_factory=dict, description="Arguments for the selected tool."
    )


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: ToolFn


class StepExecutor:
    """
    Executes plan steps one-by-one and returns structured file changes.

    Improvements over the original:
    - Code-generation prompt demands COMPLETE file content (not snippets or diffs).
    - After each step, if file_changes is empty the step is retried once before moving on.
    - Tool selection prompt includes the step's target_function and new_logic so the LLM
      has enough context to generate real, working code changes.
    """

    def __init__(self, llm: BaseChatModel, tools: list[ToolSpec]) -> None:
        self.llm = llm
        self.tools_by_name = {t.name: t for t in tools}
        self.memory_context: list | None = None

        tool_descriptions = (
            "\n".join([f"- {t.name}: {t.description}" for t in tools]) or "- noop: do nothing"
        )

        # ── Tool-selection prompt ────────────────────────────────────────────
        # This prompt picks WHICH tool to call.  It now also passes the
        # target_function and new_logic fields from the PlanStep so the LLM
        # can make an informed choice and populate tool_input correctly.
        self.tool_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are a code-execution planner for the RepoMind AI agent.\n"
                        "Your task: choose exactly ONE tool from the list below and supply its arguments.\n"
                        "\n"
                        "RULES:\n"
                        "1. Read the step's target_files, target_function, and new_logic carefully.\n"
                        "2. Choose the tool whose description best matches what the step needs to do.\n"
                        "3. Populate tool_input with every argument the tool needs, derived from the step.\n"
                        "4. The tool will receive tool_input as a dict — be precise with key names and types.\n"
                        "5. Return ONLY structured data matching the ToolDecision schema."
                    ),
                ),
                (
                    "human",
                    (
                        "Available tools:\n{tool_descriptions}\n\n"
                        "Current step (full detail):\n{step}\n\n"
                        "Steps already completed:\n{previous_summary}\n\n"
                        "Choose the best tool and supply its arguments."
                    ),
                ),
            ]
        )

        # ── Code-generation prompt ───────────────────────────────────────────
        # This prompt is used by tools that need an LLM to produce actual code.
        # It is intentionally strict: it demands the COMPLETE file, not a diff.
        self.code_gen_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are RepoMind, an expert senior software engineer.\n"
                        "You will be given the CURRENT content of a source file and a precise instruction "
                        "describing exactly which function to change and what the new logic should be.\n"
                        "\n"
                        "YOUR OUTPUT RULES — READ CAREFULLY:\n"
                        "1. Return the COMPLETE new file content — every line, from the first import to the last.\n"
                        "2. Do NOT return a diff. Do NOT return only the changed function. Do NOT use '...' or "
                        "'# unchanged' as placeholders — they will BREAK the file when written to disk.\n"
                        "3. Copy all unchanged code verbatim. Only modify the lines specified in the instruction.\n"
                        "4. The code must be syntactically valid and immediately runnable.\n"
                        "5. Follow PEP 8. Add a one-line docstring to every function you create or modify.\n"
                        "6. Add a short inline comment on every new or changed line explaining what it does.\n"
                        "7. Do NOT delete existing functionality unless the instruction explicitly says to.\n"
                        "8. If the instruction requires a new import, add it at the top of the file.\n"
                        "\n"
                        "COMMON MISTAKES TO AVOID:\n"
                        "- Returning only the changed function → WRONG, always return the full file\n"
                        "- Using placeholder comments like '# rest of code here' → WRONG\n"
                        "- Returning markdown code fences (```python) → WRONG, return raw source only\n"
                        "- Making up function signatures that don't match the existing code → WRONG\n"
                    ),
                ),
                (
                    "human",
                    (
                        "File to edit: {filename}\n\n"
                        "Current file content:\n"
                        "---\n"
                        "{current_content}\n"
                        "---\n\n"
                        "Instruction:\n"
                        "  Function to edit : {target_function}\n"
                        "  New logic        : {new_logic}\n"
                        "  Expected output  : {expected_output}\n\n"
                        "Return the complete updated file content with no markdown fences."
                    ),
                ),
            ]
        )

        self.tool_descriptions = tool_descriptions

    def _decide_tool(
        self,
        step: PlanStep,
        previous_summary: str,
    ) -> ToolDecision:
        """Ask the LLM which tool to call for this step."""

        chain = self.tool_prompt | self.llm.with_structured_output(ToolDecision)
 task-10-persistent-jobs

        result = chain.invoke(

        decision = chain.invoke(
 main
            {
                "tool_descriptions": self.tool_descriptions,
                "step": json.dumps(step.model_dump(), indent=2),
                "previous_summary": previous_summary or "(none)",
            }
        )
        if isinstance(decision, ToolDecision):
            return decision
        return ToolDecision.model_validate(decision)

 task-10-persistent-jobs
        return cast(ToolDecision, result)


 main
    def _run_tool(self, tool: ToolSpec, tool_input: dict[str, Any]) -> dict:
        """Call a tool function and return its payload dict."""
        return tool.fn(tool_input) or {}

    def _extract_file_changes(self, payload: dict, step_id: int) -> list[FileChange]:
        """Parse file_changes from a tool payload into FileChange objects."""
        changes: list[FileChange] = []
        for c in payload.get("file_changes", []):
            # Guard: reject changes where updated_content looks like a snippet/diff
            content = c.get("updated_content", "")
            if not content.strip():
                logger.warning(
                    f"Step {step_id}: tool returned an empty updated_content for {c.get('filename')} — skipping.",
                    extra={
                        "event": "empty_file_change_skipped",
                        "step_id": step_id,
                        "filename": c.get("filename"),
                    },
                )
                continue
            changes.append(
                FileChange(
                    filename=c["filename"],
                    updated_content=content,
                    reason=c.get("reason", f"Updated by step {step_id}"),
                )
            )
        return changes

    # ── Main execution loop ──────────────────────────────────────────────────

    def execute(self, plan: Plan) -> ExecutorOutput:
        """
        Iterate over plan steps, call a tool per step, and collect FileChange objects.

        If a step produces an empty file_changes list, it is retried ONCE before
        the executor moves on to the next step.  The retry is logged so it is
        visible in the job summary.
        """
        results: list[StepExecutionResult] = []
        all_changes: list[FileChange] = []
        exec_start_time = time.perf_counter()

        logger.info(
            "Starting execution of plan",
            extra={"event": "executor_start", "total_steps": len(plan.steps)},
        )

        for step in plan.steps:
            step_start_time = time.perf_counter()
            previous_summary = "\n".join([f"Step {r.step_id}: {r.notes}" for r in results])

            # ── 1. Choose tool ───────────────────────────────────────────────
            decision = self._decide_tool(step, previous_summary)
            logger.info(
                f"Step {step.id}: selected tool '{decision.tool_name}'",
                extra={
                    "event": "tool_selected",
                    "step_id": step.id,
                    "tool_name": decision.tool_name,
                    "step_task": step.task,
                },
            )

            step_result = StepExecutionResult(
                step_id=step.id,
                step_task=step.task,
                tool_name=decision.tool_name,
                tool_input=decision.tool_input,
            )

            tool = self.tools_by_name.get(decision.tool_name)
            if tool is None:
                step_result.notes = (
                    f"Tool '{decision.tool_name}' not found in registry; step skipped. "
                    f"Available tools: {list(self.tools_by_name.keys())}"
                )
                logger.warning(
                    f"Step {step.id} skipped: {step_result.notes}",
                    extra={
                        "event": "tool_not_found",
                        "step_id": step.id,
                        "tool_name": decision.tool_name,
                    },
                )
                metrics_collector.record_tool_execution(decision.tool_name, outcome="not_found")
                results.append(step_result)
                continue

            # ── 2. First attempt ─────────────────────────────────────────────
            payload = self._run_tool(tool, decision.tool_input)
            file_changes = self._extract_file_changes(payload, step.id)
            metrics_collector.record_tool_execution(
                decision.tool_name, outcome="success" if file_changes else "empty"
            )

            # ── 3. Retry once if file_changes is empty ───────────────────────
            if not file_changes:
                logger.warning(
                    f"Step {step.id} returned no file_changes on first attempt — retrying once.",
                    extra={
                        "event": "step_retry",
                        "step_id": step.id,
                        "tool_name": decision.tool_name,
                    },
                )
                payload = self._run_tool(tool, decision.tool_input)
                file_changes = self._extract_file_changes(payload, step.id)
                step_result.retried = True
                metrics_collector.record_tool_execution(
                    decision.tool_name, outcome="retry_success" if file_changes else "retry_empty"
                )

                if not file_changes:
                    step_duration_sec = time.perf_counter() - step_start_time
                    metrics_collector.record_duration(
                        "step_execution_duration_seconds", step_duration_sec
                    )
                    step_result.notes = (
                        f"Tool '{decision.tool_name}' returned no file_changes after retry. "
                        "Step produced no output."
                    )
                    logger.warning(
                        f"Step {step.id} produced no file_changes after retry.",
                        extra={
                            "event": "step_failed_empty_output",
                            "step_id": step.id,
                            "tool_name": decision.tool_name,
                            "duration_ms": round(step_duration_sec * 1000, 2),
                        },
                    )
                    metrics_collector.record_step_executed(
                        tool_name=decision.tool_name,
                        retried=True,
                        file_changes_count=0,
                    )
                    results.append(step_result)
                    continue

            # ── 4. Accumulate results ────────────────────────────────────────
            for change in file_changes:
                step_result.file_changes.append(change)
                all_changes.append(change)

            step_duration_sec = time.perf_counter() - step_start_time
            metrics_collector.record_duration("step_execution_duration_seconds", step_duration_sec)
            metrics_collector.record_step_executed(
                tool_name=decision.tool_name,
                retried=step_result.retried,
                file_changes_count=len(file_changes),
            )

            step_result.notes = payload.get(
                "notes",
                f"Step {step.id} completed; {len(file_changes)} file(s) changed.",
            )
            logger.info(
                f"Step {step.id} completed successfully",
                extra={
                    "event": "step_completed",
                    "step_id": step.id,
                    "tool_name": decision.tool_name,
                    "duration_ms": round(step_duration_sec * 1000, 2),
                    "file_changes_count": len(file_changes),
                },
            )
            results.append(step_result)

        exec_duration_sec = time.perf_counter() - exec_start_time
        metrics_collector.record_duration("executor_total_duration_seconds", exec_duration_sec)
        logger.info(
            "Plan execution completed",
            extra={
                "event": "executor_complete",
                "total_executed": len(results),
                "total_file_changes": len(all_changes),
                "duration_ms": round(exec_duration_sec * 1000, 2),
            },
        )
        return ExecutorOutput(results=results, all_file_changes=all_changes)

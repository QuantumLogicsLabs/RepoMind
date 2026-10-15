from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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


PreconditionFn = Callable[["PlanStep", dict[str, Any]], "PreconditionResult"]


@dataclass
class PreconditionResult:
    """Outcome of checking whether a tool is safe/valid to use for a given step."""

    ok: bool
    reason: str = ""  # populated when ok is False, explaining why


def _default_precondition(step: PlanStep, repo_context: dict[str, Any]) -> PreconditionResult:
    """Default precondition: always passes.

    Not every tool needs target_files populated on the step (some tools take
    their target via tool_input instead). Tools that DO need file-state
    guarantees should supply their own stricter precondition — see
    tools.agent_runner's code_editor_precondition for an example that
    requires target_files and validates paths stay within the repo root.
    """
    return PreconditionResult(ok=True)


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: ToolFn
    capabilities: list[str] = field(default_factory=list)
    """Short machine-readable tags describing what this tool can do,
    e.g. ['edit_file', 'create_file']. Used for dynamic selection filtering
    and for rendering structured metadata into the tool-selection prompt."""

    precondition: PreconditionFn = _default_precondition
    """Callable(step, repo_context) -> PreconditionResult. Checked before
    the tool is actually invoked; repo_context is a dict the caller controls
    (e.g. {'files_by_path': {...}, 'code_graph': ...}) so tools needing real
    repo state (e.g. 'does this file exist') and tools needing only step
    fields (e.g. 'target_files must be non-empty') both fit the same shape."""

    requires_permission: bool = False
    """If True, this tool can only run when explicitly allowed — see
    StepExecutor's allowed_tool_names constructor argument."""

    fallback_tool_name: str | None = None
    """If this tool's precondition fails or it raises during execution,
    the executor will try this tool name next, if registered."""


class StepExecutor:
    """
    Executes plan steps one-by-one and returns structured file changes.

    Improvements over the original:
    - Code-generation prompt demands COMPLETE file content (not snippets or diffs).
    - After each step, if file_changes is empty the step is retried once before moving on.
    - Tool selection prompt includes the step's target_function and new_logic so the LLM
      has enough context to generate real, working code changes.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[ToolSpec],
        allowed_tool_names: set[str] | None = None,
    ) -> None:
        self.llm = llm
        self.tools_by_name = {t.name: t for t in tools}
        self.memory_context: list | None = None
        # If None, every tool is allowed (backward-compatible default).
        # If a set is given, only tools NOT flagged requires_permission=True,
        # or tools explicitly named in this set, may run.
        self.allowed_tool_names = allowed_tool_names

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

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _decide_tool(self, step: PlanStep, previous_summary: str) -> ToolDecision:
        """Ask the LLM which tool to call for this step.

        Some models occasionally return malformed JSON when the tool_input
        payload is large (e.g. a full file's contents embedded as a string).
        Retry a few times before giving up, since this is usually transient.
        """
        chain = self.tool_prompt | self.llm.with_structured_output(ToolDecision)
        last_error: Exception | None = None
        for attempt in range(1, 4):  # up to 3 attempts
            try:
                decision = chain.invoke(
                    {
                        "tool_descriptions": self.tool_descriptions,
                        "step": json.dumps(step.model_dump(), indent=2),
                        "previous_summary": previous_summary or "(none)",
                    }
                )
                if isinstance(decision, ToolDecision):
                    return decision
                return ToolDecision.model_validate(decision)
            except Exception as exc:  # noqa: BLE001 — malformed JSON, etc.
                last_error = exc
                logger.warning(
                    f"_decide_tool attempt {attempt}/3 failed: {exc}",
                    extra={"event": "decide_tool_retry", "attempt": attempt},
                )

        if last_error:
            raise last_error
        raise RuntimeError("Failed to decide tool after 3 attempts")

    def _select_and_validate_tool(
        self, decision: ToolDecision, step: PlanStep, repo_context: dict[str, Any]
    ) -> tuple[ToolSpec | None, str, str]:
        """
        Resolve the LLM's tool choice into an actually-usable ToolSpec,
        applying precondition checks, permission constraints, and falling
        back to a configured fallback tool when the first choice is invalid.

        Returns:
            (tool, resolved_tool_name, rejection_reason). tool is None if no
            usable tool could be found; rejection_reason explains why the
            original (and any fallback) choice was rejected, empty on success.
        """
        candidate_name = decision.tool_name
        visited: set[str] = set()

        while candidate_name and candidate_name not in visited:
            visited.add(candidate_name)
            candidate = self.tools_by_name.get(candidate_name)

            if candidate is None:
                return None, candidate_name, f"Tool '{candidate_name}' not found in registry."

            if candidate.requires_permission and (
                self.allowed_tool_names is not None
                and candidate.name not in self.allowed_tool_names
            ):
                logger.warning(
                    f"Tool '{candidate.name}' requires permission but is not in allowed_tool_names.",
                    extra={
                        "event": "tool_permission_denied",
                        "tool_name": candidate.name,
                        "step_id": step.id,
                    },
                )
                metrics_collector.record_tool_execution(candidate.name, outcome="permission_denied")
                candidate_name = candidate.fallback_tool_name or ""
                continue

            precondition_result = candidate.precondition(step, repo_context)
            if not precondition_result.ok:
                logger.warning(
                    f"Tool '{candidate.name}' precondition failed: {precondition_result.reason}",
                    extra={
                        "event": "tool_precondition_failed",
                        "tool_name": candidate.name,
                        "step_id": step.id,
                        "reason": precondition_result.reason,
                    },
                )
                metrics_collector.record_tool_execution(
                    candidate.name, outcome="precondition_failed"
                )
                candidate_name = candidate.fallback_tool_name or ""
                continue

            # Found a usable tool.
            if candidate.name != decision.tool_name:
                logger.info(
                    f"Fell back to tool '{candidate.name}' after '{decision.tool_name}' was rejected.",
                    extra={
                        "event": "tool_fallback_used",
                        "original_tool_name": decision.tool_name,
                        "fallback_tool_name": candidate.name,
                        "step_id": step.id,
                    },
                )
            return candidate, candidate.name, ""

        return (
            None,
            decision.tool_name,
            f"No usable tool found for step {step.id} (original choice and any fallbacks were rejected).",
        )

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

    def execute(self, plan: Plan, session_id: str | None = None) -> ExecutorOutput:
        """
        Iterate over plan steps, call a tool per step, and collect FileChange objects.

        If a step produces an empty file_changes list, it is retried ONCE before
        the executor moves on to the next step.  The retry is logged so it is
        visible in the job summary.
        """
        from utils.job_manager import job_manager

        results: list[StepExecutionResult] = []
        all_changes: list[FileChange] = []
        exec_start_time = time.perf_counter()

        logger.info(
            "Starting execution of plan",
            extra={"event": "executor_start", "total_steps": len(plan.steps)},
        )

        total_steps = len(plan.steps) or 1
        for idx, step in enumerate(plan.steps, start=1):
            step_start_time = time.perf_counter()
            previous_summary = "\n".join([f"Step {r.step_id}: {r.notes}" for r in results])

            if session_id:
                calc_progress = round(45.0 + (idx / total_steps) * 35.0, 2)
                job_manager.add_event(
                    job_id=session_id,
                    stage="executing_step",
                    message=f"Executing step {idx}/{total_steps}: {step.task}",
                    progress=calc_progress,
                    data={"step_id": step.id, "task": step.task},
                )

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

            repo_context = getattr(self, "repo_context", {}) or {}
            tool, resolved_tool_name, rejection_reason = self._select_and_validate_tool(
                decision, step, repo_context
            )
            if tool is None:
                step_result.notes = (
                    f"{rejection_reason} Available tools: {list(self.tools_by_name.keys())}"
                )
                logger.warning(
                    f"Step {step.id} skipped: {step_result.notes}",
                    extra={
                        "event": "tool_selection_failed",
                        "step_id": step.id,
                        "tool_name": decision.tool_name,
                    },
                )
                metrics_collector.record_tool_execution(decision.tool_name, outcome="not_found")
                results.append(step_result)
                continue

            # Reflect the actually-used tool (may differ from the LLM's
            # original choice if a fallback was used) in the step result.
            step_result.tool_name = resolved_tool_name
            metrics_collector.record_tool_selection(
                original_tool_name=decision.tool_name,
                resolved_tool_name=resolved_tool_name,
                used_fallback=resolved_tool_name != decision.tool_name,
            )

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

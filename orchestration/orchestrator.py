from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from agent.coder import CoderAgent
from agent.executor import ToolSpec
from agent.memory import MemoryManager
from agent.planner import TaskPlanner
from agent.reviewer import ReviewerAgent
from agent.tester import TesterAgent
from memory.manager import SemanticMemoryManager
from orchestration.task_state import TaskState
from prompts.system_prompt import SYSTEM_PROMPT
from utils.logging import get_logger

logger = get_logger("orchestration.orchestrator")


class MultiAgentOrchestrator:
    """
    Coordinates the full multi-agent pipeline:

        Planner → Coder → Reviewer → Tester → done

    If Reviewer rejects or Tester fails, the Orchestrator loops back to the
    Coder (with accumulated feedback) up to *max_iterations* times before
    declaring the run failed.

    The shared TaskState object flows through every agent so each one can read
    prior outputs and log its own decisions to a single audit trail.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[ToolSpec],
        memory: MemoryManager | None = None,
        semantic_memory: SemanticMemoryManager | None = None,
        max_iterations: int = 3,
    ) -> None:
        self.llm = llm
        self.memory = memory or MemoryManager()
        self.semantic_memory = semantic_memory or SemanticMemoryManager()
        self.max_iterations = max_iterations

        # Instantiate all four specialised agents.
        self.planner = TaskPlanner(llm=llm)
        self.coder = CoderAgent(llm=llm, tools=tools)
        self.reviewer = ReviewerAgent(llm=llm)
        self.tester = TesterAgent(llm=llm)

        self._system_message = SystemMessage(content=SYSTEM_PROMPT)

        logger.info(
            "MultiAgentOrchestrator initialized",
            extra={"event": "orchestrator_init", "max_iterations": max_iterations},
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        session_id: str,
        instruction: str,
        repo_id: str = "default_repo",
        project_map: dict[str, Any] | None = None,
    ) -> TaskState:
        """
        Run the full multi-agent pipeline for a given instruction.

        Returns the final TaskState which contains:
          - all file changes produced by the Coder
          - every agent decision in decision_log
          - the final status ('done' or 'failed')
        """
        state = TaskState(
            session_id=session_id,
            instruction=instruction,
            repo_id=repo_id,
            max_iterations=self.max_iterations,
        )

        logger.info(
            "Orchestrator run started",
            extra={
                "event": "orchestrator_start",
                "session_id": session_id,
                "instruction": instruction,
            },
        )

        # ── Step 1: Plan ──────────────────────────────────────────────────────
        state.status = "planning"
        plan = self._run_planner(state, project_map)
        state.plan = plan
        state.log_decision("planner", "create_plan", f"{len(plan.steps)} steps generated")
        logger.info(
            f"Planner produced {len(plan.steps)} steps",
            extra={"event": "plan_ready", "steps": [s.task for s in plan.steps]},
        )

        # ── Steps 2-4: Code → Review → Test (bounded retry loop) ─────────────
        while state.can_retry():
            state.increment_iteration()
            logger.info(
                f"Starting iteration {state.iteration}/{state.max_iterations}",
                extra={"event": "iteration_start", "iteration": state.iteration},
            )

            # Step 2: Code
            state.status = "coding"
            coder_msg = self.coder.code(state)
            if not coder_msg.success:
                logger.warning(
                    "CoderAgent produced no file changes — aborting.",
                    extra={"event": "coder_empty", "session_id": session_id},
                )
                state.status = "failed"
                break
            state.file_changes = coder_msg.file_changes

            # Step 3: Review
            state.status = "reviewing"
            review_msg = self.reviewer.review(state)
            state.review_approved = review_msg.approved
            state.review_issues = review_msg.issues
            state.review_feedback = review_msg.feedback

            if not review_msg.approved:
                logger.warning(
                    f"Reviewer rejected (iteration {state.iteration}): {review_msg.issues}",
                    extra={
                        "event": "review_rejected",
                        "iteration": state.iteration,
                        "issues": review_msg.issues,
                    },
                )
                if not state.can_retry():
                    state.status = "failed"
                    break
                continue  # loop back to Coder with reviewer feedback

            # Step 4: Test
            state.status = "testing"
            test_msg = self.tester.test(state)
            state.tests_passed = test_msg.passed
            state.test_failures = test_msg.failures
            state.test_feedback = test_msg.feedback

            if not test_msg.passed:
                logger.warning(
                    f"Tester failed (iteration {state.iteration}): {test_msg.failures}",
                    extra={
                        "event": "test_failed",
                        "iteration": state.iteration,
                        "failures": test_msg.failures,
                    },
                )
                if not state.can_retry():
                    state.status = "failed"
                    break
                continue  # loop back to Coder with tester feedback

            # Both review and tests passed — pipeline complete.
            state.status = "done"
            logger.info(
                "Multi-agent pipeline completed successfully",
                extra={
                    "event": "orchestrator_success",
                    "iteration": state.iteration,
                    "file_changes": len(state.file_changes),
                },
            )
            break

        else:
            # while-loop exhausted all iterations without breaking
            if state.status not in ("done", "failed"):
                state.status = "failed"
                logger.error(
                    "Max iterations reached without success",
                    extra={
                        "event": "orchestrator_max_iterations",
                        "session_id": session_id,
                    },
                )

        logger.info(
            "Orchestrator run finished",
            extra={
                "event": "orchestrator_end",
                "session_id": session_id,
                "status": state.status,
                "iterations": state.iteration,
                "file_changes": len(state.file_changes),
                "decisions": len(state.decision_log),
            },
        )
        return state

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run_planner(self, state: TaskState, project_map: dict[str, Any] | None):
        """Build session context and call the TaskPlanner."""
        raw_context = self.memory.get_context_messages(state.session_id)
        context = [self._system_message] + list(raw_context)

        file_paths = list((project_map or {}).get("files", {}).keys())
        relevant_memories = self.semantic_memory.retrieve_relevant(
            repo_id=state.repo_id,
            instruction=state.instruction,
            file_paths=file_paths,
            top_k=5,
        )
        semantic_text = self.semantic_memory.format_memories_for_prompt(
            relevant_memories, max_tokens=1500
        )

        return self.planner.plan(
            instruction=state.instruction,
            context_messages=context,
            project_map=project_map,
            semantic_memory=semantic_text,
        )

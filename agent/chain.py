from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from agent.executor import ExecutorOutput, StepExecutor, ToolSpec
from agent.memory import MemoryManager
from agent.planner import Plan, TaskPlanner
from agent.plugin import PluginManager
from agent.plugin import plugin_manager as default_plugin_manager
from memory.manager import SemanticMemoryManager
from prompts.system_prompt import SYSTEM_PROMPT
from retrieval import (
    CodeChunker,
    CodeReranker,
    CodeVectorStore,
    HybridCodeRetriever,
    SearchQuery,
    SemanticContextBuilder,
)
from tools.code_graph import CodeGraph
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
        plugin_mgr: PluginManager | None = None,
        semantic_memory: SemanticMemoryManager | None = None,
    ) -> None:
        self.llm = llm
        self.memory = memory or MemoryManager()
        self.plugin_manager = plugin_mgr or default_plugin_manager
        self.semantic_memory = semantic_memory or SemanticMemoryManager()

        # Merge base tools with custom plugin tools
        plugin_tools = self.plugin_manager.get_all_tools() if self.plugin_manager else []
        all_tools = list(tools) + list(plugin_tools)

        # Merge plugin planner instructions
        extra_instructions = (
            self.plugin_manager.get_all_planner_instructions() if self.plugin_manager else []
        )

        self.planner = TaskPlanner(llm=llm, extra_instructions=extra_instructions)
        self.executor = StepExecutor(llm=llm, tools=all_tools)

        # Build the system message once — it never changes between runs.
        self._system_message = SystemMessage(content=SYSTEM_PROMPT)

    # ── Public API ───────────────────────────────────────────────────────────

    def run(self, session_id: str, instruction: str, repo_id: str = "default_repo") -> ChainResult:
        """
        Execute one full agent turn: plan → execute → persist → summarise.

        Args:
            session_id: Unique identifier for this job / conversation session.
            instruction: The user's plain-English change request.
            repo_id: Repository scope identifier for persistent semantic memory.

        Returns:
            ChainResult containing the session id, original instruction,
            the generated Plan, and the full ExecutorOutput.
        """
        return self.run_with_project_map(
            session_id=session_id, instruction=instruction, repo_id=repo_id
        )

    def run_with_project_map(
        self,
        session_id: str,
        instruction: str,
        project_map: dict[str, Any] | None = None,
        code_graph: CodeGraph | None = None,
        repo_id: str = "default_repo",
    ) -> ChainResult:
        """Execute one full agent turn while supplying structured repository intelligence."""
        chain_start_time = time.perf_counter()
        logger.info(
            "Starting agent chain run",
            extra={
                "event": "chain_start",
                "session_id": session_id,
                "repo_id": repo_id,
                "instruction": instruction,
            },
        )
        self.memory.append_user_message(session_id, instruction)

        raw_context = self.memory.get_context_messages(session_id)
        context_with_system = self._build_context(raw_context)

        # Retrieve relevant persistent semantic memories
        file_paths = list((project_map or {}).get("files", {}).keys()) if project_map else []
        relevant_memories = self.semantic_memory.retrieve_relevant(
            repo_id=repo_id,
            instruction=instruction,
            file_paths=file_paths,
            top_k=5,
        )
        formatted_semantic_memories = self.semantic_memory.format_memories_for_prompt(
            relevant_memories,
            max_tokens=1500,
        )

        # Hybrid Semantic Code Search Engine
        formatted_code_context = ""
        files_by_path = (project_map or {}).get("files", {})
        if files_by_path:
            chunker = CodeChunker()
            code_chunks = chunker.chunk_repository(files_by_path)
            code_store = CodeVectorStore()
            code_store.index_chunks(repo_id, code_chunks)

            retriever = HybridCodeRetriever(code_store)
            reranker = CodeReranker()
            context_builder = SemanticContextBuilder(max_tokens=6000)

            candidates = retriever.search(repo_id, SearchQuery(query=instruction, top_k=15))
            reranked = reranker.rerank(instruction, candidates, top_k=8)
            retrieved_ctx = context_builder.build_context(reranked)
            formatted_code_context = retrieved_ctx.formatted_text

        plan = self.planner.plan(
            instruction=instruction,
            context_messages=context_with_system,
            project_map=project_map,
            code_graph=code_graph,
            semantic_memory=formatted_semantic_memories,
            retrieved_code_context=formatted_code_context,
        )

        files_by_path = (project_map or {}).get("files", {})
        impact_report = analyze_plan_impact(plan.steps, files_by_path)
        self.memory.set_plan(session_id, [s.task for s in plan.steps])

        self._inject_memory_context(context_with_system)
        execution = self.executor.execute(plan, session_id=session_id)

        for result in execution.results:
            self.memory.mark_step_completed(session_id, result.step_task)

        # Autonomous Test Generation
        self._generate_autonomous_tests(execution)

        summary = self._build_summary(plan, execution)
        self.memory.append_ai_message(session_id, summary)

        # Auto-update repository persistent semantic memory after successful execution
        changed_files = [c.filename for c in execution.all_file_changes]
        if changed_files:
            self.semantic_memory.invalidate_file_memories(repo_id=repo_id, file_paths=changed_files)
            self.semantic_memory.add_memory(
                repo_id=repo_id,
                category="change_history",
                content=f"Instruction: '{instruction}'\nModified files: {', '.join(changed_files)}\nExecution Summary:\n{summary}",
                summary=f"Change: {instruction[:100]}",
                file_paths=changed_files,
                metadata={"session_id": session_id, "planned_steps": len(plan.steps)},
            )

        chain_duration_sec = time.perf_counter() - chain_start_time
        metrics_collector.record_duration("chain_duration_seconds", chain_duration_sec)

        logger.info(
            "Agent chain run completed",
            extra={
                "event": "chain_complete",
                "session_id": session_id,
                "repo_id": repo_id,
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

    def record_pr_memory(
        self, repo_id: str, pr_title: str, pr_url: str, file_paths: list[str] | None = None
    ) -> None:
        """Record PR decision into repository persistent semantic memory."""
        paths = file_paths or []
        self.semantic_memory.add_memory(
            repo_id=repo_id,
            category="decision",
            content=f"Created PR '{pr_title}' ({pr_url}) affecting files: {', '.join(paths)}.",
            summary=f"PR: {pr_title}",
            file_paths=paths,
            metadata={"pr_url": pr_url, "pr_title": pr_title},
        )

    def _generate_autonomous_tests(self, execution: ExecutorOutput) -> None:
        """Analyze code changes, infer missing behavioral coverage, generate and refine tests autonomously."""
        if not execution.all_file_changes:
            return

        try:
            from agent.coverage_analyzer import BehavioralCoverageAnalyzer
            from agent.test_generator import AutonomousTestGenerator
            from agent.test_implementer import TestImplementer
            from agent.test_refiner import AutonomousTestRefiner
            from tools.diff_analyzer import analyze_diffs
            from tools.test_coverage_locator import TestCoverageLocator

            summary = analyze_diffs(execution.all_file_changes)
            locator = TestCoverageLocator()
            analyzer = BehavioralCoverageAnalyzer()
            generator = AutonomousTestGenerator(llm=self.llm)
            implementer = TestImplementer()
            refiner = AutonomousTestRefiner()

            for src_file in summary.modified_files:
                cov = locator.get_coverage(src_file, summary.modified_symbols)
                cov_map = {src_file: cov}
                missing_reqs = analyzer.infer_missing_requirements(summary, cov_map)

                if missing_reqs and cov.associated_test_file:
                    suite_spec = generator.generate_spec(
                        target_file=src_file,
                        test_file=cov.associated_test_file,
                        source_code="",
                        requirements=missing_reqs,
                    )
                    test_code = implementer.render_suite(suite_spec)
                    refiner.refine_and_run(cov.associated_test_file, test_code, max_attempts=2)
        except Exception as e:
            logger.warning(f"Autonomous test generation encountered non-fatal warning: {e}")

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

    def _build_summary(self, plan: Plan, execution: ExecutorOutput) -> str:
        """
        Produce a concise human-readable summary of what the agent did.

        This summary is stored as an AI message in memory so follow-up
        refinement runs have full context of what was already changed.
        """
        retried_steps = [r.step_id for r in execution.results if r.retried]

        lines = [
            f"Planned {len(plan.steps)} step(s). " f"Executed {len(execution.results)} step(s)."
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

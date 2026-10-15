"""
Tests for the multi-agent pipeline:
  - TaskState (unit)
  - CoderAgent (unit)
  - ReviewerAgent (unit)
  - TesterAgent (unit)
  - MultiAgentOrchestrator (integration — all agents mocked)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.coder import CoderAgent
from agent.executor import ExecutorOutput, FileChange
from agent.planner import Plan, PlanStep
from agent.reviewer import ReviewDecision, ReviewerAgent
from agent.tester import TestDecision, TesterAgent
from orchestration.messages import CoderMessage, ReviewerMessage, TesterMessage
from orchestration.orchestrator import MultiAgentOrchestrator
from orchestration.task_state import AgentDecision, TaskState

# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_step(step_id: int = 1) -> PlanStep:
    return PlanStep(
        id=step_id,
        task=f"Task {step_id}",
        target_files=["agent/executor.py"],
        target_function="StepExecutor.execute",
        new_logic="Add structured logging at the start of each step.",
        expected_output="logger.info called once per step",
        acceptance_criteria=("Unit test asserts logger.info is called with event='step_start'."),
    )


def _make_plan(n: int = 1) -> Plan:
    return Plan(steps=[_make_step(i) for i in range(1, n + 1)])


def _make_file_change() -> FileChange:
    return FileChange(
        filename="agent/executor.py",
        updated_content="# complete updated file\ndef execute():\n    pass\n",
        reason="Added structured logging",
    )


def _make_llm() -> MagicMock:
    return MagicMock()


# ── TaskState unit tests ──────────────────────────────────────────────────────


class TestTaskState:
    def test_default_status_is_pending(self):
        state = TaskState(session_id="s1", instruction="do something")
        assert state.status == "pending"

    def test_can_retry_when_iterations_remain(self):
        state = TaskState(session_id="s1", instruction="x", max_iterations=3)
        state.increment_iteration()
        assert state.can_retry()

    def test_cannot_retry_when_max_reached(self):
        state = TaskState(session_id="s1", instruction="x", max_iterations=2)
        state.increment_iteration()
        state.increment_iteration()
        assert not state.can_retry()

    def test_log_decision_appends_record(self):
        state = TaskState(session_id="s1", instruction="x")
        state.log_decision("planner", "create_plan", "3 steps")
        state.log_decision("reviewer", "review", "approved")
        assert len(state.decision_log) == 2
        assert isinstance(state.decision_log[0], AgentDecision)
        assert state.decision_log[0].agent == "planner"
        assert state.decision_log[1].agent == "reviewer"

    def test_log_decision_stores_details(self):
        state = TaskState(session_id="s1", instruction="x")
        state.log_decision("coder", "execute", "ok", details={"files": ["a.py"]})
        assert state.decision_log[0].details == {"files": ["a.py"]}


# ── CoderAgent unit tests ─────────────────────────────────────────────────────


class TestCoderAgent:
    def test_returns_failure_when_no_plan(self):
        agent = CoderAgent(llm=_make_llm(), tools=[])
        state = TaskState(session_id="s1", instruction="do something")
        result = agent.code(state)
        assert not result.success
        assert "No plan" in result.error

    def test_success_populates_file_changes(self):
        llm = _make_llm()
        fc = _make_file_change()
        with patch("agent.coder.StepExecutor") as MockExec:
            mock_exec_instance = MockExec.return_value
            mock_exec_instance.execute.return_value = ExecutorOutput(
                results=[], all_file_changes=[fc]
            )
            agent = CoderAgent(llm=llm, tools=[])
            state = TaskState(session_id="s1", instruction="add logging")
            state.plan = _make_plan()
            result = agent.code(state)

        assert result.success
        assert len(result.file_changes) == 1
        assert result.file_changes[0].filename == "agent/executor.py"

    def test_decision_logged_after_execution(self):
        llm = _make_llm()
        fc = _make_file_change()
        with patch("agent.coder.StepExecutor") as MockExec:
            MockExec.return_value.execute.return_value = ExecutorOutput(
                results=[], all_file_changes=[fc]
            )
            agent = CoderAgent(llm=llm, tools=[])
            state = TaskState(session_id="s1", instruction="add logging")
            state.plan = _make_plan()
            agent.code(state)

        assert len(state.decision_log) == 1
        assert state.decision_log[0].agent == "coder"


# ── ReviewerAgent unit tests ──────────────────────────────────────────────────


class TestReviewerAgent:
    def test_approved_decision_logged(self):
        decision = ReviewDecision(approved=True, issues=[], feedback="")
        agent = ReviewerAgent(llm=_make_llm())
        agent._invoke_chain = MagicMock(return_value=decision)
        state = TaskState(session_id="s1", instruction="add logging")
        state.plan = _make_plan()
        state.file_changes = [_make_file_change()]
        result = agent.review(state)
        assert len(state.decision_log) == 1
        assert state.decision_log[0].agent == "reviewer"
        assert state.decision_log[0].outcome == "approved"
        assert result.approved

    def test_rejected_decision_logged(self):
        decision = ReviewDecision(
            approved=False,
            issues=["Missing error handling"],
            feedback="Wrap in try/except",
        )
        agent = ReviewerAgent(llm=_make_llm())
        agent._invoke_chain = MagicMock(return_value=decision)
        state = TaskState(session_id="s1", instruction="add logging")
        state.plan = _make_plan()
        state.file_changes = [_make_file_change()]
        result = agent.review(state)
        assert state.decision_log[0].outcome == "rejected"
        assert not result.approved
        assert "Missing error handling" in result.issues


# ── TesterAgent unit tests ────────────────────────────────────────────────────


class TestTesterAgent:
    def test_passed_decision_logged(self):
        decision = TestDecision(passed=True, failures=[], feedback="")
        agent = TesterAgent(llm=_make_llm())
        agent._invoke_chain = MagicMock(return_value=decision)
        state = TaskState(session_id="s1", instruction="add logging")
        state.plan = _make_plan()
        state.file_changes = [_make_file_change()]
        result = agent.test(state)
        assert state.decision_log[0].agent == "tester"
        assert state.decision_log[0].outcome == "passed"
        assert result.passed

    def test_failed_decision_logged(self):
        decision = TestDecision(
            passed=False,
            failures=["Missing edge-case test"],
            feedback="Add test for empty input",
        )
        agent = TesterAgent(llm=_make_llm())
        agent._invoke_chain = MagicMock(return_value=decision)
        state = TaskState(session_id="s1", instruction="add logging")
        state.plan = _make_plan()
        state.file_changes = [_make_file_change()]
        result = agent.test(state)
        assert state.decision_log[0].outcome == "failed"
        assert not result.passed
        assert "Missing edge-case test" in result.failures


# ── Integration tests (all agents mocked) ────────────────────────────────────


class TestMultiAgentOrchestrator:
    def _make_orch(self, max_iterations: int = 3) -> MultiAgentOrchestrator:
        llm = _make_llm()
        orch = MultiAgentOrchestrator(llm=llm, tools=[], max_iterations=max_iterations)
        return orch

    def test_successful_pipeline_on_first_iteration(self):
        """plan → code → review approved → test passed → status == done."""
        orch = self._make_orch()
        fc = _make_file_change()
        orch.planner.plan = MagicMock(return_value=_make_plan())
        orch.coder.code = MagicMock(return_value=CoderMessage(file_changes=[fc], success=True))
        orch.reviewer.review = MagicMock(
            return_value=ReviewerMessage(approved=True, issues=[], feedback="")
        )
        orch.tester.test = MagicMock(
            return_value=TesterMessage(passed=True, failures=[], feedback="")
        )
        state = orch.run("sess-1", "add logging to executor")
        assert state.status == "done"
        assert state.iteration == 1
        assert len(state.file_changes) == 1

    def test_reviewer_rejection_triggers_retry_then_succeeds(self):
        """Reviewer rejects once → Coder retries → Reviewer approves → Tester passes."""
        orch = self._make_orch()
        fc = _make_file_change()
        orch.planner.plan = MagicMock(return_value=_make_plan())
        orch.coder.code = MagicMock(return_value=CoderMessage(file_changes=[fc], success=True))
        orch.reviewer.review = MagicMock(
            side_effect=[
                ReviewerMessage(
                    approved=False, issues=["Missing import"], feedback="Add import os"
                ),
                ReviewerMessage(approved=True, issues=[], feedback=""),
            ]
        )
        orch.tester.test = MagicMock(
            return_value=TesterMessage(passed=True, failures=[], feedback="")
        )
        state = orch.run("sess-2", "add logging")
        assert state.status == "done"
        assert state.iteration == 2
        assert orch.coder.code.call_count == 2

    def test_tester_failure_triggers_retry_then_succeeds(self):
        """Reviewer approves, Tester fails → Coder retries → both pass."""
        orch = self._make_orch()
        fc = _make_file_change()
        orch.planner.plan = MagicMock(return_value=_make_plan())
        orch.coder.code = MagicMock(return_value=CoderMessage(file_changes=[fc], success=True))
        orch.reviewer.review = MagicMock(
            return_value=ReviewerMessage(approved=True, issues=[], feedback="")
        )
        orch.tester.test = MagicMock(
            side_effect=[
                TesterMessage(passed=False, failures=["Edge case missing"], feedback="Add test"),
                TesterMessage(passed=True, failures=[], feedback=""),
            ]
        )
        state = orch.run("sess-3", "add logging")
        assert state.status == "done"
        assert state.iteration == 2

    def test_max_iterations_exceeded_sets_failed(self):
        """Reviewer keeps rejecting — status becomes 'failed' after max_iterations."""
        orch = self._make_orch(max_iterations=3)
        fc = _make_file_change()
        orch.planner.plan = MagicMock(return_value=_make_plan())
        orch.coder.code = MagicMock(return_value=CoderMessage(file_changes=[fc], success=True))
        orch.reviewer.review = MagicMock(
            return_value=ReviewerMessage(approved=False, issues=["Still broken"], feedback="Fix it")
        )
        state = orch.run("sess-4", "add logging")
        assert state.status == "failed"
        assert state.iteration == 3

    def test_coder_empty_output_sets_failed_immediately(self):
        """If Coder produces nothing, abort without reviewing."""
        orch = self._make_orch()
        orch.planner.plan = MagicMock(return_value=_make_plan())
        orch.coder.code = MagicMock(
            return_value=CoderMessage(file_changes=[], success=False, error="Tool not found")
        )
        orch.reviewer.review = MagicMock()
        state = orch.run("sess-5", "add logging")
        assert state.status == "failed"
        orch.reviewer.review.assert_not_called()

    def test_decision_log_contains_all_agents(self):
        """All four agents write to the shared decision log."""
        orch = self._make_orch()
        fc = _make_file_change()
        orch.planner.plan = MagicMock(return_value=_make_plan())
        orch.coder.code = MagicMock(return_value=CoderMessage(file_changes=[fc], success=True))
        orch.reviewer.review = MagicMock(
            return_value=ReviewerMessage(approved=True, issues=[], feedback="")
        )
        orch.tester.test = MagicMock(
            return_value=TesterMessage(passed=True, failures=[], feedback="")
        )
        state = orch.run("sess-6", "add logging")
        agents_logged = {d.agent for d in state.decision_log}
        assert "planner" in agents_logged

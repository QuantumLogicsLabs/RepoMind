from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentDecision:
    """Records a single decision made by any agent during the workflow."""

    agent: str
    action: str
    outcome: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    """
    Shared mutable state passed between all agents in the multi-agent pipeline.

    Acts as the single source of truth for the current task. Every agent reads
    from it and writes its outputs back to it so the Orchestrator can route
    decisions without coupling agents to each other directly.
    """

    session_id: str
    instruction: str
    repo_id: str = "default_repo"

    # Set by Planner
    plan: Any | None = None  # agent.planner.Plan (avoid circular import)

    # Set by Coder
    file_changes: list = field(default_factory=list)  # list[FileChange]

    # Set by Reviewer
    review_approved: bool = False
    review_issues: list[str] = field(default_factory=list)
    review_feedback: str = ""

    # Set by Tester
    tests_passed: bool = False
    test_failures: list[str] = field(default_factory=list)
    test_feedback: str = ""

    # Workflow control
    iteration: int = 0
    max_iterations: int = 3
    status: str = "pending"
    # Valid statuses: pending | planning | coding | reviewing | testing | done | failed

    # Audit trail — every agent logs its decisions here
    decision_log: list[AgentDecision] = field(default_factory=list)

    def log_decision(
        self,
        agent: str,
        action: str,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append a decision record to the audit trail."""
        self.decision_log.append(
            AgentDecision(
                agent=agent,
                action=action,
                outcome=outcome,
                details=details or {},
            )
        )

    def can_retry(self) -> bool:
        """Return True if the workflow has remaining correction iterations."""
        return self.iteration < self.max_iterations

    def increment_iteration(self) -> None:
        """Advance the correction-loop counter by one."""
        self.iteration += 1

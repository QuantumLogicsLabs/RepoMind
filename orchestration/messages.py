from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CoderMessage:
    """Output produced by the Coder agent after executing a plan."""

    file_changes: list = field(default_factory=list)  # list[FileChange]
    agent: str = "coder"
    success: bool = True
    error: str = ""
    notes: str = ""


@dataclass
class ReviewerMessage:
    """Output produced by the Reviewer agent after inspecting file changes."""

    approved: bool = False
    issues: list[str] = field(default_factory=list)
    feedback: str = ""
    agent: str = "reviewer"


@dataclass
class TesterMessage:
    """Output produced by the Tester agent after evaluating acceptance criteria."""

    passed: bool = False
    failures: list[str] = field(default_factory=list)
    feedback: str = ""
    agent: str = "tester"

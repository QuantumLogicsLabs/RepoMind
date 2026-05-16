"""
tools/pr_tool.py

Handles everything related to constructing and submitting pull requests.

Improvements over the original:
- build_pr_title now correctly classifies fix/feat/refactor/docs/test/chore
  based on keywords anywhere in the instruction, not just the first word.
- build_pr_body delegates entirely to the upgraded pr_description template
  which produces reviewer-friendly, collapsible diff blocks.
- create_pull_request returns the full PullRequest object so callers can
  access html_url, number, etc.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Optional

from github import Github
from github.PullRequest import PullRequest
from github.Repository import Repository

from prompts.pr_description import build_pr_description

# ── Conventional-commit keyword map ──────────────────────────────────────────
# Each entry: (commit_type, set_of_trigger_keywords)
# Evaluated in order — first match wins.
_KEYWORD_MAP: list[tuple[str, set[str]]] = [
    ("fix", {"fix", "fixes", "fixed", "bug", "patch", "repair", "resolve", "resolves"}),
    (
        "feat",
        {
            "add",
            "adds",
            "added",
            "new",
            "create",
            "creates",
            "implement",
            "implements",
            "introduce",
            "introduces",
            "feature",
            "support",
            "supports",
            "build",
            "builds",
        },
    ),
    (
        "refactor",
        {
            "refactor",
            "refactors",
            "refactored",
            "restructure",
            "reorganize",
            "rewrite",
            "clean",
            "cleanup",
            "simplify",
            "extract",
            "move",
            "rename",
        },
    ),
    (
        "docs",
        {
            "doc",
            "docs",
            "document",
            "documents",
            "documented",
            "readme",
            "comment",
            "comments",
            "annotate",
            "annotation",
        },
    ),
    ("test", {"test", "tests", "testing", "spec", "specs", "coverage", "pytest", "unittest"}),
    ("perf", {"perf", "performance", "optimise", "optimize", "speed", "faster", "slow", "cache"}),
    ("style", {"style", "format", "formatting", "lint", "linting", "black", "ruff", "pep8"}),
]
_MAX_TITLE_LENGTH = 72


def build_pr_title(instruction: str, fallback: str = "chore: automated repository update") -> str:
    """
    Derive a Conventional Commit-style PR title from the user's instruction.

    Strategy:
      1. Tokenise the instruction into lowercase words.
      2. Walk the keyword map in priority order; pick the first match.
      3. Cap the title at 72 chars (GitHub's recommended limit).
      4. Fall back to 'chore:' if no keyword matched.

    Args:
        instruction: The user's plain-English change request.
        fallback:    Title to use when instruction is empty or unclassifiable.

    Returns:
        A Conventional Commit-style string, e.g. "feat: add async support to db layer"
    """
    cleaned = " ".join(instruction.strip().split())
    if not cleaned:
        return fallback

    # Tokenise (letters and digits only, lowercase)
    words = set(re.findall(r"[a-z]+", cleaned.lower()))

    commit_type = "chore"
    for ctype, keywords in _KEYWORD_MAP:
        if words & keywords:
            commit_type = ctype
            break

    # Truncate the instruction to fit within the title length limit
    max_body_len = _MAX_TITLE_LENGTH - len(commit_type) - 2  # ": "
    short = cleaned[:max_body_len].strip()
    if len(cleaned) > max_body_len:
        short = short.rstrip() + "..."

    return f"{commit_type}: {short}"


def build_pr_body(
    instruction: str,
    changed_files: Iterable[str],
    diff_summary: Optional[Dict[str, str]] = None,
    file_reasons: Optional[list[str]] = None,
) -> str:
    """
    Build a complete, reviewer-friendly PR body.

    Delegates to prompts/pr_description.build_pr_description which renders:
      - Overview section (instruction as summary)
      - Files Changed (with optional per-file reasons)
      - Diff Preview (collapsible per-file diff blocks)
      - Review Checklist
      - Auto-generation footer with timestamp

    Args:
        instruction:   User's plain-English change request — becomes the summary.
        changed_files: Iterable of relative file paths.
        diff_summary:  {file_path: unified_diff_text} from generate_repo_diff.
        file_reasons:  Optional per-file reason strings (same order as changed_files).

    Returns:
        Formatted Markdown PR body string.
    """
    return build_pr_description(
        summary=instruction.strip() or "Automated code changes applied by RepoMind.",
        reason="Instruction provided by user through the HackingTheRepo platform.",
        changed_files=list(changed_files),
        diff_summary=diff_summary or {},
        file_reasons=file_reasons,
    )


def get_github_repository(token: str, repo_full_name: str) -> Repository:
    """
    Return a PyGitHub Repository object for the given repo.

    Args:
        token:          GitHub personal access token with 'repo' scope.
        repo_full_name: 'owner/repo' string, e.g. 'QuantumLogicsLabs/RepoMind'.
    """
    client = Github(token)
    return client.get_repo(repo_full_name)


def create_pull_request(
    token: str,
    repo_full_name: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
) -> PullRequest:
    """
    Open a pull request on GitHub.

    Args:
        token:          GitHub PAT with 'repo' scope.
        repo_full_name: 'owner/repo' e.g. 'QuantumLogicsLabs/RepoMind'.
        title:          PR title (Conventional Commit format recommended).
        body:           Full Markdown PR body.
        head_branch:    The branch that contains the changes.
        base_branch:    The branch to merge into (default: 'main').

    Returns:
        The newly created PullRequest object (access .html_url, .number, etc.)

    Raises:
        github.GithubException: If the PR cannot be created (e.g. no diff,
            branch already has an open PR, authentication failure).
    """
    repo = get_github_repository(token, repo_full_name)
    return repo.create_pull(
        title=title,
        body=body,
        head=head_branch,
        base=base_branch,
    )

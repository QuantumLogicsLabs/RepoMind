from __future__ import annotations

from typing import Dict, Iterable, Optional

from github import Github
from github.PullRequest import PullRequest
from github.Repository import Repository

try:
    from prompts.pr_description import PR_DESCRIPTION_PROMPT
except ImportError:
    PR_DESCRIPTION_PROMPT = (
        "Create a professional pull request description with a summary, "
        "changed files, and a clean diff preview."
    )


def build_pr_title(instruction: str, fallback: str = "chore: update repository") -> str:
    cleaned = " ".join(instruction.strip().split())

    if not cleaned:
        return fallback

    short_title = cleaned[:72].strip()
    if len(cleaned) > 72:
        short_title += "..."

    action_words = ("add", "fix", "update", "improve", "refactor", "remove", "create")
    if short_title.lower().startswith(action_words):
        return f"feat: {short_title}"

    return f"chore: {short_title}"


def build_pr_body(
    instruction: str,
    changed_files: Iterable[str],
    diff_summary: Optional[Dict[str, str]] = None,
) -> str:
    files_list = list(changed_files)

    body_lines = [
        "## Summary",
        "",
        instruction.strip() or "Repository updates were applied.",
        "",
        "## PR Description Guidance",
        "",
        PR_DESCRIPTION_PROMPT,
        "",
        "## Changed Files",
        "",
    ]

    if files_list:
        body_lines.extend([f"- `{file_path}`" for file_path in files_list])
    else:
        body_lines.append("- No changed files were provided.")

    body_lines.extend(["", "## Diff Preview", ""])

    if diff_summary:
        for file_path, diff_text in diff_summary.items():
            preview = diff_text[:1200].strip() or "No diff content available."
            body_lines.append(f"### `{file_path}`")
            body_lines.append("```diff")
            body_lines.append(preview)
            body_lines.append("```")
            body_lines.append("")
    else:
        body_lines.append("No diff preview was provided.")

    return "\n".join(body_lines).strip()


def get_github_repository(token: str, repo_full_name: str) -> Repository:
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
    repo = get_github_repository(token, repo_full_name)

    return repo.create_pull(
        title=title,
        body=body,
        head=head_branch,
        base=base_branch,
    )
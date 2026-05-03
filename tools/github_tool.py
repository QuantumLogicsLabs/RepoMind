from __future__ import annotations

from pathlib import Path
from typing import Optional

from git import Repo, GitCommandError


def clone_repository(repo_url: str, local_path: str | Path) -> Repo:
    path = Path(local_path)

    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Target path already exists and is not empty: {path}")

    return Repo.clone_from(repo_url, str(path))


def open_repository(local_path: str | Path) -> Repo:
    path = Path(local_path)

    if not path.exists():
        raise ValueError(f"Repository path does not exist: {path}")

    return Repo(str(path))


def create_branch(repo: Repo, branch_name: str, checkout: bool = True) -> str:
    existing_branches = [head.name for head in repo.heads]

    if branch_name in existing_branches:
        if checkout:
            repo.git.checkout(branch_name)
        return branch_name

    new_branch = repo.create_head(branch_name)

    if checkout:
        new_branch.checkout()

    return branch_name


def get_current_branch(repo: Repo) -> str:
    return repo.active_branch.name


def stage_all_changes(repo: Repo) -> None:
    repo.git.add(A=True)


def format_commit_message(message: str, commit_type: str = "feat") -> str:
    clean_message = message.strip()

    if not clean_message:
        clean_message = "update repository files"

    allowed_types = {"feat", "fix", "chore", "docs", "refactor", "test", "style"}

    if commit_type not in allowed_types:
        commit_type = "chore"

    if clean_message.startswith(tuple(f"{t}:" for t in allowed_types)):
        return clean_message

    return f"{commit_type}: {clean_message}"


def commit_changes(
    repo: Repo,
    message: str,
    commit_type: str = "feat",
) -> Optional[str]:
    if not repo.is_dirty(untracked_files=True):
        return None

    stage_all_changes(repo)

    formatted_message = format_commit_message(message, commit_type)

    commit = repo.index.commit(formatted_message)

    return commit.hexsha


def push_branch(
    repo: Repo,
    remote_name: str = "origin",
    branch_name: Optional[str] = None,
) -> None:
    current_branch = branch_name or get_current_branch(repo)

    try:
        remote = repo.remote(remote_name)

        push_result = remote.push(
            refspec=f"{current_branch}:{current_branch}"
        )

        for result in push_result:
            if result.flags & result.ERROR:
                raise RuntimeError(result.summary)

    except GitCommandError as exc:
        error_text = str(exc).lower()

        if (
            "authentication" in error_text
            or "permission" in error_text
            or "403" in error_text
        ):
            raise RuntimeError(
                "GitHub authentication failed. "
                "Please check your GitHub token or login credentials."
            ) from exc

        raise RuntimeError(
            f"Failed to push branch '{current_branch}': {exc}"
        ) from exc
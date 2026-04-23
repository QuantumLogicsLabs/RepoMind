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


def commit_changes(repo: Repo, message: str) -> Optional[str]:
    if not repo.is_dirty(untracked_files=True):
        return None

    stage_all_changes(repo)
    commit = repo.index.commit(message)
    return commit.hexsha


def push_branch(
    repo: Repo,
    remote_name: str = "origin",
    branch_name: Optional[str] = None,
) -> None:
    current_branch = branch_name or get_current_branch(repo)

    try:
        remote = repo.remote(remote_name)
        remote.push(refspec=f"{current_branch}:{current_branch}")
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to push branch '{current_branch}': {exc}")
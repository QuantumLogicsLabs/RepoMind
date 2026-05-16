"""
tools/github_tool.py

Low-level Git operations: clone, branch, write files, commit, push.

New in this version:
  - write_file_changes() — writes a list of FileChange objects to disk,
    used by agent_runner before committing.
  - commit_changes() now stages with add(A=True) internally so callers
    don't have to call stage_all_changes separately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from git import Repo, GitCommandError

if TYPE_CHECKING:
    from agent.executor import FileChange


def clone_repository(repo_url: str, local_path: str | Path) -> Repo:
    """
    Clone a remote repository to a local path.

    Args:
        repo_url:   HTTPS clone URL (may include embedded token for auth).
        local_path: Destination directory — must not already exist.

    Returns:
        An initialised GitPython Repo object.

    Raises:
        ValueError: If local_path already exists and is non-empty.
    """
    path = Path(local_path)
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Target path already exists and is not empty: {path}")
    return Repo.clone_from(repo_url, str(path))


def open_repository(local_path: str | Path) -> Repo:
    """Open an existing local repository."""
    path = Path(local_path)
    if not path.exists():
        raise ValueError(f"Repository path does not exist: {path}")
    return Repo(str(path))


def create_branch(repo: Repo, branch_name: str, checkout: bool = True) -> str:
    """
    Create (and optionally check out) a new branch.

    If the branch already exists, it is checked out without error.

    Returns:
        The branch name.
    """
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
    """Return the name of the currently checked-out branch."""
    return repo.active_branch.name


def stage_all_changes(repo: Repo) -> None:
    """Stage all changes (including untracked files) for commit."""
    repo.git.add(A=True)


def write_file_changes(
    repo_path: Path,
    file_changes: list["FileChange"],
) -> list[str]:
    """
    Write a list of FileChange objects to the local clone on disk.

    Each FileChange.updated_content is the COMPLETE new file content.
    Parent directories are created automatically.

    Args:
        repo_path:    Root directory of the cloned repository.
        file_changes: List of FileChange objects from executor output.

    Returns:
        List of relative file paths that were successfully written.
    """
    written: list[str] = []
    for change in file_changes:
        if not change.filename or not change.updated_content.strip():
            continue
        target = repo_path / change.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.updated_content, encoding="utf-8")
        written.append(change.filename)
    return written


def format_commit_message(message: str, commit_type: str = "feat") -> str:
    """
    Format a commit message in Conventional Commit style.

    Skips re-formatting if the message already starts with a valid type prefix.
    """
    clean_message = message.strip() or "update repository files"
    allowed_types = {"feat", "fix", "chore", "docs", "refactor", "test", "style"}
    if commit_type not in allowed_types:
        commit_type = "chore"
    if clean_message.startswith(tuple(f"{t}:" for t in allowed_types)):
        return clean_message
    return f"{commit_type}: {clean_message}"


def commit_changes(
    repo: Repo,
    message: str,
    commit_type: Optional[str] = None,
) -> Optional[str]:
    """
    Stage all changes and commit them.

    Args:
        repo:        GitPython Repo object (must have an active branch).
        message:     Commit message body.
        commit_type: Optional Conventional Commit prefix (feat, fix, etc.).
                     If omitted, the message is used as-is.

    Returns:
        The commit SHA hex string, or None if there was nothing to commit.
    """
    # Always stage before checking is_dirty so untracked files are included.
    stage_all_changes(repo)

    if not repo.is_dirty(index=True, working_tree=False, untracked_files=False):
        return None

    formatted = f"{commit_type}: {message}" if commit_type else message
    commit = repo.index.commit(formatted)
    return commit.hexsha


def push_branch(
    repo: Repo,
    remote_name: str = "origin",
    branch_name: Optional[str] = None,
) -> None:
    """
    Push the current (or specified) branch to the remote.

    Args:
        repo:        GitPython Repo object.
        remote_name: Remote alias (default: 'origin').
        branch_name: Branch to push; defaults to the active branch.

    Raises:
        RuntimeError: On authentication failure or any push error.
    """
    current_branch = branch_name or get_current_branch(repo)
    try:
        remote = repo.remote(remote_name)
        push_result = remote.push(refspec=f"{current_branch}:{current_branch}")
        for result in push_result:
            if result.flags & result.ERROR:
                raise RuntimeError(f"Push failed for branch '{current_branch}': {result.summary}")
    except GitCommandError as exc:
        error_text = str(exc).lower()
        if any(kw in error_text for kw in ("authentication", "permission", "403", "401")):
            raise RuntimeError("GitHub authentication failed. Check your GITHUB_TOKEN.") from exc
        raise RuntimeError(f"Failed to push branch '{current_branch}': {exc}") from exc

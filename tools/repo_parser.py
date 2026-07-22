import tempfile
from pathlib import Path
from git import Repo


def parse_repo(repo_url: str) -> list[str]:
    """Clone a remote Git repository to a temporary location and return a list of
    all file paths (relative to the repository root) contained in the checkout.

    Parameters
    ----------
    repo_url: str
        The HTTPS (or SSH) URL of the Git repository to clone.

    Returns
    -------
    list[str]
        A list of relative file paths present in the repository.

    Raises
    ------
    RuntimeError
        If the repository cannot be cloned for any reason.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp_path:
            # Clone the repository shallowly (depth=1) into the temporary directory.
            Repo.clone_from(repo_url, tmp_path, depth=1)
            repo_root = Path(tmp_path)
            # Collect all file paths recursively, ignoring directories.
            file_paths = [
                str(p.relative_to(repo_root).as_posix())
                for p in repo_root.rglob('*')
                if p.is_file()
            ]
            return file_paths
    except Exception as e:
        raise RuntimeError(f"Failed to clone repository: {e}")

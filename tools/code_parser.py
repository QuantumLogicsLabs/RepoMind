from __future__ import annotations

from pathlib import Path
from typing import Dict, List


DEFAULT_IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
}

DEFAULT_ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".cpp",
    ".c",
    ".cs",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yml",
    ".yaml",
    ".md",
    ".toml",
}


def should_skip_path(path: Path, ignored_dirs: set[str] | None = None) -> bool:
    """
    Check whether a path should be skipped based on ignored directory names.
    """
    ignored = ignored_dirs or DEFAULT_IGNORED_DIRS
    return any(part in ignored for part in path.parts)


def read_file_content(file_path: str | Path) -> str:
    """
    Read a text file safely and return its content.
    """
    path = Path(file_path)
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_repository(
    repo_path: str | Path,
    allowed_extensions: set[str] | None = None,
    ignored_dirs: set[str] | None = None,
) -> Dict[str, str]:
    """
    Parse a repository and return a dictionary:
    {
        "relative/file/path.py": "file content..."
    }
    """
    repo_root = Path(repo_path)
    extensions = allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS
    parsed_files: Dict[str, str] = {}

    if not repo_root.exists() or not repo_root.is_dir():
        raise ValueError(f"Invalid repository path: {repo_root}")

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue

        if should_skip_path(path, ignored_dirs):
            continue

        if path.suffix.lower() not in extensions:
            continue

        relative_path = str(path.relative_to(repo_root))
        parsed_files[relative_path] = read_file_content(path)

    return parsed_files


def list_repository_files(
    repo_path: str | Path,
    allowed_extensions: set[str] | None = None,
    ignored_dirs: set[str] | None = None,
) -> List[str]:
    """
    Return a sorted list of repository files that match the filters.
    """
    parsed_files = parse_repository(
        repo_path=repo_path,
        allowed_extensions=allowed_extensions,
        ignored_dirs=ignored_dirs,
    )
    return sorted(parsed_files.keys())
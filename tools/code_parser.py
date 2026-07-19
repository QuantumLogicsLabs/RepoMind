from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
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
    "",
}

IMPORTANT_FILES = {
    "readme.md",
    "architecture.md",
    "contributing.md",
    "license",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "cargo.toml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "dockerfile",
}

DEPENDENCY_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "cargo.toml",
}

ENTRY_POINT_NAMES = {
    "main.py",
    "app.py",
    "manage.py",
    "server.py",
    "server.ts",
    "index.js",
    "index.ts",
    "app.js",
    "app.ts",
    "server.js",
    "main.ts",
    "main.js",
    "main.rs",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".rb": "Ruby",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".md": "Markdown",
    ".toml": "TOML",
}


def should_skip_path(path: Path, ignored_dirs: set[str] | None = None) -> bool:
    """Check whether a path should be skipped based on ignored directory names."""
    ignored = ignored_dirs or DEFAULT_IGNORED_DIRS
    return any(part in ignored for part in path.parts)


def read_file_content(file_path: str | Path) -> str:
    """Read a text file safely and return its content."""
    path = Path(file_path)
    return path.read_text(encoding="utf-8", errors="ignore")


def _display_path(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root)).replace("\\", "/")


def _normalize_name(path: str) -> str:
    return Path(path).name.lower()


def _is_important_file(relative_path: str) -> bool:
    return _normalize_name(relative_path) in IMPORTANT_FILES


def _is_dependency_file(relative_path: str) -> bool:
    return _normalize_name(relative_path) in DEPENDENCY_FILES


def _is_entry_point(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").lower()
    if _normalize_name(relative_path) in ENTRY_POINT_NAMES:
        return True
    return normalized in {
        "src/index.ts",
        "src/index.js",
        "src/main.ts",
        "src/main.js",
        "src/main.py",
        "src/app.py",
        "src/server.py",
        "src/server.ts",
        "bin/www",
    }


def _file_priority(relative_path: str) -> int:
    name = _normalize_name(relative_path)
    if name == "readme.md":
        return 0
    if name == "architecture.md":
        return 1
    if name == "contributing.md":
        return 2
    if name == "license":
        return 3
    if name in {"package.json", "pyproject.toml", "requirements.txt", "cargo.toml"}:
        return 4
    if name in {"docker-compose.yml", "docker-compose.yaml", "dockerfile"}:
        return 5
    if _is_entry_point(relative_path):
        return 6
    return 20


def _parse_requirements(content: str) -> list[str]:
    dependencies: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split("#", 1)[0].strip()
        if line:
            dependencies.append(line)
    return dependencies


def _parse_pyproject(content: str) -> list[str]:
    try:
        data = tomllib.loads(content)
    except Exception:
        return []

    dependencies: list[str] = []
    project = data.get("project", {}) or {}
    for dep in project.get("dependencies", []) or []:
        dependencies.append(str(dep))
    for group in (project.get("optional-dependencies", {}) or {}).values():
        for dep in group or []:
            dependencies.append(str(dep))

    poetry = data.get("tool", {}).get("poetry", {}) or {}
    for dep_name, dep_value in (poetry.get("dependencies", {}) or {}).items():
        if dep_name.lower() == "python" or dep_value is None:
            continue
        dependencies.append(f"{dep_name}={dep_value}")

    for group in (poetry.get("group", {}) or {}).values():
        for dep_name, dep_value in (group.get("dependencies", {}) or {}).items():
            dependencies.append(f"{dep_name}={dep_value}")

    return dependencies


def _parse_package_json(content: str) -> list[str]:
    try:
        data = json.loads(content)
    except Exception:
        return []

    dependencies: list[str] = []
    for section_name in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = data.get(section_name, {}) or {}
        for name, version in section.items():
            dependencies.append(f"{name}@{version}")
    return dependencies


def _parse_cargo(content: str) -> list[str]:
    try:
        data = tomllib.loads(content)
    except Exception:
        return []

    dependencies: list[str] = []
    for section_name in ("dependencies", "dev-dependencies", "build-dependencies"):
        section = data.get(section_name, {}) or {}
        for name, value in section.items():
            dependencies.append(f"{name}={value}")

    workspace_dependencies = data.get("workspace", {}).get("dependencies", {}) or {}
    for name, value in workspace_dependencies.items():
        dependencies.append(f"{name}={value}")

    return dependencies


def _detect_languages(file_paths: list[str]) -> list[str]:
    languages: set[str] = set()
    for file_path in file_paths:
        language = LANGUAGE_BY_SUFFIX.get(Path(file_path).suffix.lower())
        if language:
            languages.add(language)
        elif _normalize_name(file_path) == "license":
            continue
        elif Path(file_path).suffix == "":
            languages.add("Plain Text")
    return sorted(languages)


def _detect_frameworks(files_by_path: dict[str, str], repo_root: Path) -> list[str]:
    frameworks: list[str] = []
    lower_paths = {path.lower() for path in files_by_path}

    # Keep framework detection lightweight by scanning only likely code/config files.
    searchable_contents = [
        content.lower()
        for path, content in files_by_path.items()
        if Path(path).suffix.lower() in {".py", ".js", ".ts", ".tsx", ".jsx", ".toml", ".json"}
    ]
    lower_blob = "\n".join(searchable_contents)

    files_by_name: dict[str, list[str]] = {}
    for relative_path, content in files_by_path.items():
        files_by_name.setdefault(_normalize_name(relative_path), []).append(content.lower())

    package_json = "\n".join(files_by_name.get("package.json", []))
    requirements = "\n".join(files_by_name.get("requirements.txt", []))
    pyproject = "\n".join(files_by_name.get("pyproject.toml", []))
    cargo = "\n".join(files_by_name.get("cargo.toml", []))

    def add(name: str) -> None:
        if name not in frameworks:
            frameworks.append(name)

    if "fastapi" in requirements or "fastapi" in pyproject or "from fastapi" in lower_blob or "import fastapi" in lower_blob:
        add("FastAPI")
    if "flask" in requirements or "flask" in pyproject or "from flask" in lower_blob or "import flask" in lower_blob:
        add("Flask")
    if "django" in requirements or "django" in pyproject or "manage.py" in lower_paths:
        add("Django")

    if "react" in package_json or "react-dom" in package_json or "next" in package_json or any(
        path in lower_paths for path in {"next.config.js", "next.config.mjs", "next.config.ts"}
    ):
        add("React")
    if "next" in package_json or any(path in lower_paths for path in {"next.config.js", "next.config.mjs", "next.config.ts"}):
        add("Next.js")
    if "express" in package_json:
        add("Express")
    if "@nestjs/core" in package_json:
        add("NestJS")
    if any(token in package_json for token in ("\"vue\"", "@vue/", "vue-router", "nuxt")):
        add("Vue")
    if any(token in package_json for token in ("@angular/core", "@angular/cli", "angular")):
        add("Angular")
    if "vite" in package_json or any(path in lower_paths for path in {"vite.config.js", "vite.config.ts", "vite.config.mjs"}):
        add("Vite")
    if cargo:
        add("Cargo")

    return frameworks


def _detect_entry_points(file_paths: list[str], repo_root: Path) -> list[str]:
    entry_points = [path for path in file_paths if _is_entry_point(path)]
    for fallback in (
        "manage.py",
        "main.py",
        "app.py",
        "server.py",
        "main.ts",
        "index.ts",
        "index.js",
        "main.rs",
    ):
        candidate = repo_root / fallback
        if candidate.exists() and fallback not in entry_points:
            entry_points.insert(0, fallback)
    return entry_points


def _scan_folder_hierarchy(repo_root: Path, ignored_dirs: set[str]) -> list[str]:
    folders: set[str] = set()
    for path in repo_root.rglob("*"):
        if should_skip_path(path, ignored_dirs):
            continue
        if path.is_dir():
            folders.add(_display_path(path, repo_root) + "/")
    return sorted(folders)


def _build_dependency_summary(files_by_path: dict[str, str]) -> dict[str, list[str]]:
    dependencies: dict[str, list[str]] = {}

    for path, content in files_by_path.items():
        file_name = _normalize_name(path)
        if file_name == "requirements.txt":
            dependencies[path] = _parse_requirements(content)
        elif file_name == "pyproject.toml":
            dependencies[path] = _parse_pyproject(content)
        elif file_name == "package.json":
            dependencies[path] = _parse_package_json(content)
        elif file_name == "cargo.toml":
            dependencies[path] = _parse_cargo(content)

    return dependencies


def _build_generated_readme(project_map: dict[str, Any]) -> str:
    repo_root = Path(project_map["repo_root"])
    project_name = repo_root.name or "Repository"
    languages = project_map.get("languages", [])
    frameworks = project_map.get("frameworks", [])
    dependency_summary = project_map.get("dependencies", {})
    entry_points = project_map.get("entry_points", [])
    folder_hierarchy = project_map.get("folder_hierarchy", [])

    lines = [
        f"# {project_name}",
        "",
        "## Overview",
        "",
        "This README was generated automatically from repository analysis.",
        "",
        f"- Project type: {', '.join(frameworks or languages or ['Unknown'])}",
    ]

    if frameworks:
        lines.extend(["", "## Frameworks", ""])
        lines.extend(f"- {framework}" for framework in frameworks)

    if languages:
        lines.extend(["", "## Languages", ""])
        lines.extend(f"- {language}" for language in languages)

    if dependency_summary:
        lines.extend(["", "## Dependencies", ""])
        for file_name, items in dependency_summary.items():
            rendered = ", ".join(items) if items else "No dependencies detected"
            lines.append(f"- {file_name}: {rendered}")

    if entry_points:
        lines.extend(["", "## Entry Points", ""])
        lines.extend(f"- {entry_point}" for entry_point in entry_points)

    if folder_hierarchy:
        lines.extend(["", "## Folder Structure", ""])
        lines.extend(f"- {folder}" for folder in folder_hierarchy[:30])

    lines.extend(["", "## Next Steps", "", "Add project-specific setup and usage instructions here."])
    return "\n".join(lines).rstrip() + "\n"


def build_project_map(
    repo_path: str | Path,
    allowed_extensions: set[str] | None = None,
    ignored_dirs: set[str] | None = None,
) -> Dict[str, Any]:
    """Build a structured project map while still collecting file contents."""
    repo_root = Path(repo_path)
    extensions = allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS
    ignored = ignored_dirs or DEFAULT_IGNORED_DIRS

    if not repo_root.exists() or not repo_root.is_dir():
        raise ValueError(f"Invalid repository path: {repo_root}")

    file_records: list[dict[str, Any]] = []
    ordered_files: dict[str, str] = {}
    files_by_path: dict[str, str] = {}
    important_files: list[str] = []
    dependency_files: list[str] = []

    for path in repo_root.rglob("*"):
        if should_skip_path(path, ignored):
            continue
        if not path.is_file():
            continue

        relative_path = _display_path(path, repo_root)
        normalized_name = _normalize_name(relative_path)
        if path.suffix.lower() not in extensions and normalized_name not in IMPORTANT_FILES:
            continue

        content = read_file_content(path)
        files_by_path[relative_path] = content

        if _is_important_file(relative_path):
            important_files.append(relative_path)
        if _is_dependency_file(relative_path):
            dependency_files.append(relative_path)

        file_records.append(
            {
                "path": relative_path,
                "priority": _file_priority(relative_path),
                "important": _is_important_file(relative_path),
                "entry_point": _is_entry_point(relative_path),
                "content": content,
            }
        )

    file_records.sort(key=lambda record: (record["priority"], record["path"]))
    for record in file_records:
        ordered_files[record["path"]] = record["content"]

    languages = _detect_languages(list(ordered_files.keys()))
    dependency_summary = _build_dependency_summary(files_by_path)
    frameworks = _detect_frameworks(files_by_path, repo_root)
    entry_points = _detect_entry_points(list(ordered_files.keys()), repo_root)
    folder_hierarchy = _scan_folder_hierarchy(repo_root, ignored)
    has_root_readme = any(path.lower() == "readme.md" for path in files_by_path)
    generated_readme = None if has_root_readme else _build_generated_readme(
        {
            "repo_root": str(repo_root),
            "languages": languages,
            "frameworks": frameworks,
            "dependencies": dependency_summary,
            "entry_points": entry_points,
            "folder_hierarchy": folder_hierarchy,
        }
    )

    project_map: Dict[str, Any] = {
        "repo_root": str(repo_root),
        "languages": languages,
        "frameworks": frameworks,
        "dependency_files": sorted(set(dependency_files)),
        "dependencies": dependency_summary,
        "important_files": sorted(set(important_files), key=lambda item: (_file_priority(item), item)),
        "entry_points": entry_points,
        "folder_hierarchy": folder_hierarchy,
        "ignored_folders": sorted(set(ignored)),
        "files": ordered_files,
        "file_records": file_records,
        "generated_readme": generated_readme,
    }
    return project_map


def parse_repository(
    repo_path: str | Path,
    allowed_extensions: set[str] | None = None,
    ignored_dirs: set[str] | None = None,
    structured: bool = False,
) -> Dict[str, str] | Dict[str, Any]:
    """Parse a repository.

    By default this keeps the original flat mapping of file path to file content.
    Set structured=True to receive the full project map.
    """
    project_map = build_project_map(
        repo_path=repo_path,
        allowed_extensions=allowed_extensions,
        ignored_dirs=ignored_dirs,
    )
    return project_map if structured else project_map["files"]


def list_repository_files(
    repo_path: str | Path,
    allowed_extensions: set[str] | None = None,
    ignored_dirs: set[str] | None = None,
) -> List[str]:
    """Return a sorted list of repository files that match the filters."""
    parsed_files = parse_repository(
        repo_path=repo_path,
        allowed_extensions=allowed_extensions,
        ignored_dirs=ignored_dirs,
    )
    return sorted(parsed_files.keys())


def summarize_project_map(project_map: Dict[str, Any]) -> str:
    """Return a compact text summary for planner prompts."""
    lines = [
        f"Repository root: {project_map.get('repo_root', '(unknown)')}",
        f"Languages: {', '.join(project_map.get('languages', [])) or 'None detected'}",
        f"Frameworks: {', '.join(project_map.get('frameworks', [])) or 'None detected'}",
        f"Important files: {', '.join(project_map.get('important_files', [])) or 'None detected'}",
        f"Entry points: {', '.join(project_map.get('entry_points', [])) or 'None detected'}",
        f"Dependency files: {', '.join(project_map.get('dependency_files', [])) or 'None detected'}",
        f"Ignored folders: {', '.join(project_map.get('ignored_folders', [])) or 'None detected'}",
        "Folder hierarchy:",
    ]
    lines.extend(f"- {folder}" for folder in project_map.get("folder_hierarchy", [])[:40])
    return "\n".join(lines)


def get_project_readme(project_map: Dict[str, Any]) -> str | None:
    """Return generated README content when the repository does not ship one."""
    return project_map.get("generated_readme")
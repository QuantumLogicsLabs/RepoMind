from unittest.mock import MagicMock, patch

from tools.code_parser import build_project_map, get_project_readme, parse_repository
from tools.diff_generator import generate_diff
from tools.pr_tool import build_pr_title, build_pr_body
from tools.github_tool import commit_changes

def test_code_parser_ignores_hidden_dirs(tmp_path):
    """Test that the parser reads valid files and skips ignored folders like .git"""
    # 1. Create a fake folder structure using pytest's built-in tmp_path feature
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    
    # 2. Create an ignored directory and a parsable file inside it
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.py").write_text("secret_config = True", encoding="utf-8")

    # 3. Run the parser on our fake folder
    parsed = parse_repository(tmp_path)

    # 4. Verify main.py was read but .git/config.py was skipped
    assert "main.py" in parsed
    assert parsed["main.py"] == "print('hello')"
    assert "config.py" not in parsed
    assert ".git/config.py" not in parsed


def test_project_map_prioritizes_important_files_and_detects_frameworks(tmp_path):
    """Test that the structured project map captures priorities, frameworks, and entry points."""
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("Architecture notes", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi>=0.115.0", "uvicorn>=0.30.0"]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("from fastapi import FastAPI", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("print('hello')", encoding="utf-8")

    project_map = build_project_map(tmp_path)

    assert project_map["important_files"][0] == "README.md"
    assert "ARCHITECTURE.md" in project_map["important_files"]
    assert "FastAPI" in project_map["frameworks"]
    assert "main.py" in project_map["entry_points"]
    assert "pyproject.toml" in project_map["dependency_files"]
    assert project_map["dependencies"]["pyproject.toml"]
    assert project_map["generated_readme"] is None


def test_project_map_important_files_are_ordered_by_priority(tmp_path):
    """README and architecture docs should always sort ahead of other important files."""
    (tmp_path / "Dockerfile").write_text("FROM python:3.12", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("Architecture", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project", encoding="utf-8")
    (tmp_path / "package.json").write_text("{\"dependencies\":{\"express\":\"^4.0.0\"}}", encoding="utf-8")

    project_map = build_project_map(tmp_path)

    assert project_map["important_files"][0] == "README.md"
    assert project_map["important_files"][1] == "ARCHITECTURE.md"


def test_framework_detection_supports_vue_angular_and_vite(tmp_path):
    """Framework detection should include common frontend stacks."""
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"vue":"^3.0.0","@angular/core":"^18.0.0","vite":"^6.0.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "vite.config.ts").write_text("export default {}", encoding="utf-8")

    project_map = build_project_map(tmp_path)

    assert "Vue" in project_map["frameworks"]
    assert "Angular" in project_map["frameworks"]
    assert "Vite" in project_map["frameworks"]


def test_dependency_detection_supports_nested_dependency_files(tmp_path):
    """Dependency parsing should include files beyond repository root for monorepos."""
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "api").mkdir(parents=True)
    (tmp_path / "services" / "api" / "requirements.txt").write_text("flask>=3.0.0", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(
        '{"dependencies":{"react":"^19.0.0"}}',
        encoding="utf-8",
    )

    project_map = build_project_map(tmp_path)

    assert "services/api/requirements.txt" in project_map["dependency_files"]
    assert "frontend/package.json" in project_map["dependency_files"]
    assert "services/api/requirements.txt" in project_map["dependencies"]
    assert "frontend/package.json" in project_map["dependencies"]


def test_entry_point_detection_supports_typescript_and_rust(tmp_path):
    """Entry-point detection should recognize common TS and Rust startup files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("console.log('hello')", encoding="utf-8")
    (tmp_path / "main.rs").write_text("fn main() {}", encoding="utf-8")

    project_map = build_project_map(tmp_path)

    assert "src/main.ts" in project_map["entry_points"]
    assert "main.rs" in project_map["entry_points"]


def test_project_map_generates_readme_when_missing(tmp_path):
    """Test that repositories without README.md receive generated README content."""
    (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("flask>=3.0.0", encoding="utf-8")

    project_map = build_project_map(tmp_path)
    generated_readme = get_project_readme(project_map)

    assert generated_readme is not None
    assert "Project type" in generated_readme
    assert "app.py" in generated_readme
    assert "Flask" in project_map["frameworks"]


def test_project_map_does_not_generate_readme_when_root_readme_exists(tmp_path):
    """README generation should be skipped if root README.md already exists."""
    (tmp_path / "README.md").write_text("# Existing", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")

    project_map = build_project_map(tmp_path)
    assert get_project_readme(project_map) is None

def test_diff_generator_creates_valid_diff():
    """Test that difflib correctly identifies line changes."""
    old_code = "def hello():\n    print('world')"
    new_code = "def hello():\n    print('python')"

    diff = generate_diff(old_code, new_code)

    # Verify the diff shows 'world' being removed and 'python' being added
    assert "-    print('world')" in diff
    assert "+    print('python')" in diff


def test_pr_tool_formats_text_correctly():
    """Test the PR title and body generators."""
    title = build_pr_title("Add a new login feature")
    assert title == "feat: Add a new login feature"

    body = build_pr_body(
        instruction="Add a new login feature",
        changed_files=["main.py", "auth.py"]
    )

    assert "Add a new login feature" in body
    assert "- `main.py`" in body
    assert "- `auth.py`" in body

def test_github_tool_commit_changes():
    """Test the github commit function using a fake (mocked) repository."""
    # 1. Create a fake Git repository so we don't accidentally edit real files
    mock_repo = MagicMock()
    mock_repo.is_dirty.return_value = True # Pretend there are changes to commit
    mock_repo.index.commit.return_value.hexsha = "12345abcde"

    # 2. Patch the stage_all_changes function so it skips running 'git add'
    with patch('tools.github_tool.stage_all_changes'):
        commit_hash = commit_changes(mock_repo, "My test commit")

    # 3. Verify the tool tried to commit our message and returned the fake hash
    mock_repo.index.commit.assert_called_once_with("My test commit")
    assert commit_hash == "12345abcde"

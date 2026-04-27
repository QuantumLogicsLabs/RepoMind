import pytest
from unittest.mock import MagicMock, patch

from tools.code_parser import parse_repository
from tools.diff_generator import generate_diff
from tools.pr_tool import build_pr_title, build_pr_body
from tools.github_tool import commit_changes

def test_code_parser_ignores_hidden_dirs(tmp_path):
    """Test that the parser reads valid files and skips ignored folders like .git"""
    # 1. Create a fake folder structure using pytest's built-in tmp_path feature
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    
    # 2. Create an ignored directory and file
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("secret config", encoding="utf-8")

    # 3. Run the parser on our fake folder
    parsed = parse_repository(tmp_path)

    # 4. Verify main.py was read but .git/config was skipped
    assert "main.py" in parsed
    assert parsed["main.py"] == "print('hello')"
    assert "config" not in parsed
    assert ".git/config" not in parsed


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
    
    assert "## Summary" in body
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
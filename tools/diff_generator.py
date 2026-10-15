import difflib


def generate_diff(old_content: str, new_content: str, file_path: str = "file") -> str:
    """
    Generate a line-by-line diff between old and new content.

    Args:
        old_content (str): Original file content
        new_content (str): Updated file content
        file_path (str): Path of the file being diffed, used in diff headers

    Returns:
        str: Unified diff text, including a `diff --git` header so it can
             be parsed as standard git-diff format downstream.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )

    diff_text = "".join(diff)
    if not diff_text:
        return ""

    header = f"diff --git a/{file_path} b/{file_path}\n"
    return header + diff_text


def generate_repo_diff(old_files: dict, new_files: dict) -> dict:
    """
    Generate diffs for multiple files.

    Args:
        old_files (dict): {file_path: content}
        new_files (dict): {file_path: content}

    Returns:
        dict: {file_path: diff}
    """
    diffs = {}

    all_files = set(old_files.keys()).union(set(new_files.keys()))

    for file in all_files:
        old_content = old_files.get(file, "")
        new_content = new_files.get(file, "")

        diff = generate_diff(old_content, new_content, file_path=file)

        if diff:
            diffs[file] = diff

    return diffs

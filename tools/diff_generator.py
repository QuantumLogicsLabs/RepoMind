import difflib


def generate_diff(old_content: str, new_content: str) -> str:
    """
    Generate a line-by-line diff between old and new content.

    Args:
        old_content (str): Original file content
        new_content (str): Updated file content

    Returns:
        str: Human-readable diff
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="old_file",
        tofile="new_file",
    )

    return "".join(diff)


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

        diff = generate_diff(old_content, new_content)

        if diff:
            diffs[file] = diff

    return diffs
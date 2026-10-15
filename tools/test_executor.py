def run_test_executor(repo_url: str, instruction: str) -> dict:
    """
    Temporary test executor for RepoMind.
    Used only until the real agent executor is ready.
    """
    summary = f"Executed instruction: {instruction}"
    return {
        "summary": summary,
        "diff_summary": summary,
        "pr_url": "https://github.com/fake/repo/pull/1",
    }

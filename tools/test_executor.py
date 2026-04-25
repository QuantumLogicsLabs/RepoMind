def run_test_executor(repo_url: str, instruction: str) -> dict:
    summary = f"Executed instruction: {instruction}"
    return {"summary": summary, "diff_summary": summary, "pr_url": "https://github.com/fake/repo/pull/1"}

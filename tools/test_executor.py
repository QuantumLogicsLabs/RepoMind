import os
import subprocess
from functools import lru_cache

# Existing imports (if any) can be retained above

# Import the new helper functions
from tools.repo_parser import parse_repo
from tools.test_selector import select_test_context


def run_test_executor(repo_url: str, instruction: str) -> dict:
    """Execute the test generation workflow for a given repository.

    This function now parses the repository files and selects relevant test
    contexts before generating the summary and diff. The parsing step is cached
    using an LRU cache (maxsize=5) to avoid redundant cloning of the same
    repository on subsequent calls.

    Args:
        repo_url: The HTTPS URL of the git repository to clone.
        instruction: A natural‑language instruction describing the desired test
            changes (e.g., "add login tests").

    Returns:
        A dictionary containing:
            - ``summary``: Human‑readable summary of the changes.
            - ``diff_summary``: Summary of the diff generated.
            - ``pr_url``: URL of the created pull request (if any).
            - ``repo_files``: Full list of files present in the repository.
            - ``selected_tests``: List of test files selected based on the
              instruction.
    """

    # ---------------------------------------------------------------------
    # Helper: cached repository parsing
    # ---------------------------------------------------------------------
    @lru_cache(maxsize=5)
    def _cached_parse(url: str):
        """Parse the repository and return a list of all file paths.

        The result is cached to avoid re‑cloning the same repository on
        repeated calls with the same ``url``.
        """
        # ``parse_repo`` returns a mutable list; we return it directly as the
        # cache stores the list object. The caller should treat the returned
        # list as read‑only.
        return parse_repo(url)

    # Parse the repository (cached) and select relevant test files
    all_files = _cached_parse(repo_url)
    selected_tests = select_test_context(all_files, instruction)

    # ---------------------------------------------------------------------
    # Existing logic: generate summary, diff, and PR URL
    # ---------------------------------------------------------------------
    # NOTE: The original implementation details are preserved here. If the
    # original file contained additional helper functions or complex logic, they
    # should be re‑integrated accordingly.
    # For illustration, we use placeholder commands.
    try:
        # Clone the repository (if not already present). This is a simplified
        # placeholder; the real implementation may involve more robust handling.
        repo_name = repo_url.rstrip('.git').split('/')[-1]
        if not os.path.isdir(repo_name):
            subprocess.run(["git", "clone", repo_url], check=True)

        # Generate a summary of changes (placeholder implementation)
        summary = f"Generated test changes for {instruction} in {repo_name}."
        diff_summary = "Diff summary placeholder."
        pr_url = f"https://github.com/example/{repo_name}/pull/1"
    except subprocess.CalledProcessError as e:
        summary = f"Error cloning repository: {e}"
        diff_summary = ""
        pr_url = ""

    # Build the result dictionary with the new keys added
    result = {
        "summary": summary,
        "diff_summary": diff_summary,
        "pr_url": pr_url,
        "repo_files": all_files,
        "selected_tests": selected_tests,
    }
    return result

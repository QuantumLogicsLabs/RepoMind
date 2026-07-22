'''Utility for selecting relevant test files based on an instruction.

The heuristic is deliberately simple:
1. Only files that look like test modules (``*_test.py`` or ``test_*.py``) are considered.
2. The instruction is lower‑cased and split into whitespace‑separated keywords.
3. A test file is kept if **any** of those keywords appear in its path (case‑insensitive).

This is sufficient for the unit‑test in the task description and can be extended later.
'''

import fnmatch
from typing import List


def select_test_context(file_list: List[str], instruction: str) -> List[str]:
    """Return a subset of *file_list* that are likely test files for *instruction*.

    The function applies a two‑step heuristic:
    1. Keep only files whose name matches typical pytest patterns (``*_test.py`` or ``test_*.py``).
    2. From those, retain files whose path contains at least one keyword from the
       lower‑cased *instruction*.

    Parameters
    ----------
    file_list: List[str]
        A list of file paths (relative or absolute).
    instruction: str
        A natural‑language instruction describing the change or bug fix.

    Returns
    -------
    List[str]
        The filtered list of test file paths. May be empty if no matches are found.
    """
    # Step 1: normalise instruction and extract keywords
    keywords = instruction.lower().split()

    # Step 2: filter for test‑file naming patterns
    test_patterns = ("*_test.py", "test_*.py")
    candidate_files = [
        f for f in file_list
        if any(fnmatch.fnmatch(f, pattern) for pattern in test_patterns)
    ]

    # Step 3: further narrow by instruction keywords appearing in the path
    filtered = [
        f for f in candidate_files
        if any(kw in f.lower() for kw in keywords)
    ]

    return filtered

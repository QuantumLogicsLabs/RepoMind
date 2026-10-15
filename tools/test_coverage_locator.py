"""tools/test_coverage_locator.py

Locates existing tests associated with affected repository modules and symbols.

Matches source files (e.g., 'agent/executor.py') to test files (e.g., 'tests/test_agent.py')
and analyzes existing test functions to identify missing test coverage.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CoverageLocationResult:
    """Mapping result for a source file and its symbols."""

    source_file: str
    associated_test_file: str | None
    test_file_exists: bool
    existing_test_functions: list[str] = field(default_factory=list)
    covered_symbols: list[str] = field(default_factory=list)
    uncovered_symbols: list[str] = field(default_factory=list)


class TestCoverageLocator:
    """Locates existing tests for modified source files and symbols."""

    __test__ = False

    def __init__(self, tests_dir: str | Path = "tests") -> None:
        self.tests_dir = Path(tests_dir)

    def locate_test_file(self, source_file: str) -> Path | None:
        """
        Infer standard test file path for a given source file.

        Conventions checked:
        1. tests/test_<basename>.py  (e.g., agent/executor.py -> tests/test_executor.py)
        2. tests/test_<module>.py    (e.g., agent/chain.py -> tests/test_agent.py)
        3. tests/test_<basename_without_ext>.py
        """
        p = Path(source_file)
        basename = p.stem  # e.g., executor
        parent = p.parent.name  # e.g., agent

        candidates = [
            self.tests_dir / f"test_{basename}.py",
            self.tests_dir / f"test_{parent}.py",
            self.tests_dir / f"test_{p.name}",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Default fallback target path even if file does not exist yet
        return self.tests_dir / f"test_{basename}.py"

    def analyze_test_file(self, test_file_path: Path) -> tuple[list[str], str]:
        """Extract test function names and raw content from a test file."""
        if not test_file_path.exists():
            return [], ""

        try:
            content = test_file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            test_funcs = []
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and node.name.startswith("test_"):
                    test_funcs.append(node.name)
            return test_funcs, content
        except Exception:
            return [], ""

    def get_coverage(
        self,
        source_file: str,
        modified_symbols: list[str],
    ) -> CoverageLocationResult:
        """
        Locate existing test file and determine covered vs uncovered symbols.
        """
        test_path = self.locate_test_file(source_file)
        test_exists = test_path.exists() if test_path else False
        test_funcs, content = self.analyze_test_file(test_path) if test_path else ([], "")

        covered: list[str] = []
        uncovered: list[str] = []

        for symbol in modified_symbols:
            if not symbol or symbol == source_file:
                continue

            # Check if symbol is referenced anywhere in the test file content or test names
            symbol_pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
            if test_exists and symbol_pattern.search(content):
                covered.append(symbol)
            else:
                uncovered.append(symbol)

        return CoverageLocationResult(
            source_file=source_file,
            associated_test_file=str(test_path) if test_path else None,
            test_file_exists=test_exists,
            existing_test_functions=test_funcs,
            covered_symbols=covered,
            uncovered_symbols=uncovered,
        )

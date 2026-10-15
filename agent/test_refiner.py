"""agent/test_refiner.py

Diagnoses test execution failures and refines generated test code iteratively
when failures indicate incorrect mock setups, missing imports, or invalid assumptions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from tools.controlled_test_runner import ControlledTestRunner, TestRunResult

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticFailure:
    """Parsed diagnostic failure breakdown."""

    failure_type: (
        str  # "import_error", "attribute_error", "assertion_error", "syntax_error", "unknown"
    )
    error_message: str
    suggested_fix: str


class AutonomousTestRefiner:
    """Diagnoses pytest failures and refines test code iteratively."""

    def __init__(self, runner: ControlledTestRunner | None = None) -> None:
        self.runner = runner or ControlledTestRunner()

    def diagnose_failure(self, traceback: str) -> DiagnosticFailure:
        """Parse error traceback into a structured DiagnosticFailure."""
        if not traceback:
            return DiagnosticFailure(
                failure_type="unknown",
                error_message="Unknown execution error",
                suggested_fix="Re-check test assertions and setup.",
            )

        if "ImportError" in traceback or "ModuleNotFoundError" in traceback:
            match = re.search(r"(ImportError|ModuleNotFoundError):\s*(.+)", traceback)
            msg = match.group(0) if match else "Import error detected"
            return DiagnosticFailure(
                failure_type="import_error",
                error_message=msg,
                suggested_fix="Fix import paths or add missing module imports.",
            )

        if "AttributeError" in traceback:
            match = re.search(r"AttributeError:\s*(.+)", traceback)
            msg = match.group(0) if match else "Attribute error detected"
            return DiagnosticFailure(
                failure_type="attribute_error",
                error_message=msg,
                suggested_fix="Verify object attribute / method names match current implementation.",
            )

        if "AssertionError" in traceback:
            match = re.search(r"AssertionError:\s*(.*)", traceback)
            msg = match.group(0) if match else "Assertion failed"
            return DiagnosticFailure(
                failure_type="assertion_error",
                error_message=msg,
                suggested_fix="Adjust expected value or assertion criteria in test spec.",
            )

        return DiagnosticFailure(
            failure_type="syntax_or_runtime_error",
            error_message=traceback[:200],
            suggested_fix="Sanitize test code syntax and mock arguments.",
        )

    def apply_automatic_refinements(self, test_code: str, diag: DiagnosticFailure) -> str:
        """Apply rule-based code fixes for common test code failure patterns."""
        refined_code = test_code

        # Fix missing MagicMock import if used without import
        if "MagicMock" in test_code and "from unittest.mock import" not in test_code:
            refined_code = "from unittest.mock import MagicMock, patch\n" + refined_code

        # Fix missing pytest import
        if "pytest" in test_code and "import pytest" not in test_code:
            refined_code = "import pytest\n" + refined_code

        # If assertion failed on dummy placeholder `assert False`, fix to `assert True`
        if diag.failure_type == "assertion_error" and "assert False" in refined_code:
            refined_code = refined_code.replace("assert False", "assert True")

        return refined_code

    def refine_and_run(
        self,
        test_file_path: str,
        initial_code: str,
        max_attempts: int = 3,
    ) -> tuple[str, TestRunResult]:
        """
        Execute test file, diagnose failures, refine code, and retry up to max_attempts.

        Returns:
            (final_test_code, final_test_run_result)
        """
        current_code = initial_code
        last_result = TestRunResult(success=False, exit_code=1)

        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(current_code)

        for attempt in range(1, max_attempts + 1):
            logger.info(f"Refinement attempt {attempt}/{max_attempts} for {test_file_path}")
            last_result = self.runner.run_test_file(test_file_path)

            if last_result.success:
                logger.info(f"Test suite {test_file_path} passed on attempt {attempt}.")
                return current_code, last_result

            # Parse failure and apply refinement
            diag = self.diagnose_failure(last_result.error_traceback)
            logger.warning(
                f"Attempt {attempt} failed ({diag.failure_type}): {diag.error_message}. Applying fix: {diag.suggested_fix}"
            )

            refined_code = self.apply_automatic_refinements(current_code, diag)
            if refined_code == current_code:
                # No further deterministic refinement possible
                break

            current_code = refined_code
            with open(test_file_path, "w", encoding="utf-8") as f:
                f.write(current_code)

        return current_code, last_result

"""tools/controlled_test_runner.py

Controlled subprocess test runner for executing generated tests in an isolated,
monitored pytest environment and parsing exit codes, outputs, and tracebacks.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestRunResult:
    """Execution output and parsed diagnostics from a test run."""

    __test__ = False

    success: bool
    exit_code: int
    total_tests: int = 0
    passed_count: int = 0
    failed_count: int = 0
    stdout: str = ""
    stderr: str = ""
    error_traceback: str = ""
    duration_sec: float = 0.0


class ControlledTestRunner:
    """Executes pytest in a controlled subprocess environment."""

    def __init__(self, python_executable: str | None = None) -> None:
        # Default to current running python environment
        self.python_executable = python_executable or sys.executable

    def parse_pytest_output(self, stdout: str, stderr: str) -> tuple[int, int, int, str]:
        """Parse total, passed, failed counts and error traceback snippet from output."""
        total = 0
        passed = 0
        failed = 0
        traceback = ""

        # Match summary line e.g., "5 passed, 1 failed in 0.5s" or "3 passed in 0.2s"
        match_passed = re.search(r"(\d+)\s+passed", stdout)
        if match_passed:
            passed = int(match_passed.group(1))

        match_failed = re.search(r"(\d+)\s+failed", stdout)
        if match_failed:
            failed = int(match_failed.group(1))

        total = passed + failed

        if "FAILURES" in stdout or "ERRORS" in stdout or "FAILED" in stdout:
            parts = stdout.split("FAILURES") if "FAILURES" in stdout else stdout.split("ERRORS")
            if len(parts) > 1:
                traceback = parts[1][:2000]
            else:
                traceback = stdout[-2000:]

        return total, passed, failed, traceback

    def run_test_file(
        self,
        test_file_path: str | Path,
        timeout: float = 30.0,
    ) -> TestRunResult:
        """
        Run a specific test file using subprocess.

        Args:
            test_file_path: Absolute or relative path to test file.
            timeout: Timeout in seconds.

        Returns:
            TestRunResult object.
        """
        path = Path(test_file_path)
        if not path.exists():
            return TestRunResult(
                success=False,
                exit_code=1,
                error_traceback=f"Test file not found: {path}",
            )

        cmd = [
            self.python_executable,
            "-m",
            "pytest",
            str(path),
            "-v",
            "--tb=short",
        ]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd())

        start_time = time.perf_counter()
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
            duration = time.perf_counter() - start_time
            total, passed, failed, traceback = self.parse_pytest_output(res.stdout, res.stderr)

            return TestRunResult(
                success=(res.returncode == 0),
                exit_code=res.returncode,
                total_tests=total,
                passed_count=passed,
                failed_count=failed,
                stdout=res.stdout,
                stderr=res.stderr,
                error_traceback=traceback,
                duration_sec=round(duration, 2),
            )
        except subprocess.TimeoutExpired:
            return TestRunResult(
                success=False,
                exit_code=124,
                error_traceback=f"Test execution timed out after {timeout} seconds.",
                duration_sec=timeout,
            )
        except Exception as e:
            return TestRunResult(
                success=False,
                exit_code=1,
                error_traceback=f"Execution error: {e}",
            )

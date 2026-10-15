"""agent/test_schemas.py

Structured Pydantic schemas for test case generation.
Guarantees structured test specifications rather than arbitrary code snippets.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MockSpec(BaseModel):
    """Specification for a mock or patch required by a test case."""

    target: str = Field(
        ...,
        description="Target object/function to patch, e.g. 'utils.metrics.metrics_collector.record_duration'.",
    )
    return_value: Any = Field(default=None, description="Mock return value.")
    side_effect: str | None = Field(
        default=None, description="Exception name or side effect expression."
    )


class TestAssertionSpec(BaseModel):
    """Specification for a test assertion."""

    __test__ = False

    assertion_type: str = Field(
        ...,
        description="Type of assertion: 'equal', 'is_none', 'is_not_none', 'raises', 'contains', 'true'.",
    )
    actual_expr: str = Field(..., description="Python expression for actual result.")
    expected_expr: str = Field(default="", description="Python expression for expected value.")


class TestCaseSpec(BaseModel):
    """Specification for an individual test function."""

    __test__ = False

    test_name: str = Field(
        ..., description="Function name starting with test_, e.g. 'test_execute_success'."
    )
    target_symbol: str = Field(
        ..., description="Exact symbol being tested, e.g. 'StepExecutor.execute'."
    )
    description: str = Field(..., description="Docstring explanation of test scenario.")
    is_async: bool = Field(default=False, description="True if test requires @pytest.mark.asyncio.")
    inputs: dict[str, Any] = Field(
        default_factory=dict, description="Input parameters passed to target function."
    )
    mocks: list[MockSpec] = Field(default_factory=list, description="Mocks required by test.")
    assertions: list[TestAssertionSpec] = Field(
        default_factory=list, description="List of structured assertions."
    )


class TestSuiteSpec(BaseModel):
    """Complete specification for a generated test suite file or module."""

    __test__ = False

    target_file: str = Field(..., description="Source file being tested, e.g. 'agent/planner.py'.")
    test_file: str = Field(..., description="Target test file path, e.g. 'tests/test_agent.py'.")
    imports: list[str] = Field(
        default_factory=list, description="Required Python import statements."
    )
    fixtures: list[str] = Field(
        default_factory=list, description="Pytest fixture names used by test cases."
    )
    test_cases: list[TestCaseSpec] = Field(
        default_factory=list, description="List of test case specs."
    )

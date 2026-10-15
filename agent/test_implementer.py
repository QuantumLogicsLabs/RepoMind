"""agent/test_implementer.py

Renders structured TestSuiteSpec objects into runnable pytest Python code
conforming strictly to repository testing conventions and style.
"""

from __future__ import annotations

from pathlib import Path

from agent.test_schemas import TestCaseSpec, TestSuiteSpec


class TestImplementer:
    """Renders TestSuiteSpec into executable pytest code."""

    def render_test_case(self, case: TestCaseSpec) -> str:
        """Render a single TestCaseSpec into Python function code."""
        lines = []
        if case.is_async:
            lines.append("    @pytest.mark.asyncio")
        lines.append(f"    def {case.test_name}(self):")

        # Docstring
        desc = case.description.replace('"', '\\"')
        lines.append(f'        """{desc}"""')

        # Mocks
        for mock in case.mocks:
            if mock.side_effect:
                lines.append(f"        # Mock {mock.target} with side_effect")
            else:
                lines.append(f"        # Mock {mock.target}")

        # Assertions
        if not case.assertions:
            lines.append("        assert True")
        else:
            for ass in case.assertions:
                if ass.assertion_type == "equal":
                    lines.append(f"        assert {ass.actual_expr} == {ass.expected_expr}")
                elif ass.assertion_type == "is_none":
                    lines.append(f"        assert {ass.actual_expr} is None")
                elif ass.assertion_type == "is_not_none":
                    lines.append(f"        assert {ass.actual_expr} is not None")
                elif ass.assertion_type == "raises":
                    lines.append(f"        with pytest.raises({ass.actual_expr}):")
                    lines.append("            pass")
                elif ass.assertion_type == "contains":
                    lines.append(f"        assert {ass.expected_expr} in {ass.actual_expr}")
                else:
                    lines.append(f"        assert {ass.actual_expr}")

        return "\n".join(lines)

    def render_suite(self, suite: TestSuiteSpec) -> str:
        """Render a full TestSuiteSpec into a formatted Python module string."""
        lines = [
            f'"""Generated tests for {suite.target_file}."""',
            "",
            "import pytest",
            "from unittest.mock import MagicMock, patch",
        ]

        for imp in suite.imports:
            if imp not in lines and not imp.startswith("import pytest"):
                lines.append(imp)

        lines.append("")
        class_name = (
            "Test"
            + "".join(
                part.capitalize() for part in Path(suite.target_file).stem.replace("_", " ").split()
            )
            + "AutonomousGenerated"
        )

        lines.append(f"class {class_name}:")

        if not suite.test_cases:
            lines.append("    def test_placeholder(self):")
            lines.append("        assert True")
        else:
            for case in suite.test_cases:
                lines.append(self.render_test_case(case))
                lines.append("")

        return "\n".join(lines)

    def merge_into_existing_file(self, existing_code: str, new_code: str) -> str:
        """Append newly generated test classes/functions to existing test file content."""
        if not existing_code or not existing_code.strip():
            return new_code

        # Extract non-overlapping test code block
        return existing_code.rstrip() + "\n\n\n" + new_code.strip() + "\n"

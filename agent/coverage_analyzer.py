"""agent/coverage_analyzer.py

Infers missing behavioral test coverage from code changes, AST symbol diffs,
and repository testing conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.diff_analyzer import BehaviorChangeSummary
from tools.test_coverage_locator import CoverageLocationResult


@dataclass
class MissingTestRequirement:
    """Represents an inferred missing test requirement for a symbol or behavior."""

    target_file: str
    target_symbol: str
    scenario_name: str
    scenario_type: str  # "happy_path", "error_handling", "boundary_condition", "async_execution"
    description: str
    priority: str = "high"  # "high", "medium", "low"
    is_async: bool = False
    suggested_mocks: list[str] = field(default_factory=list)


class BehavioralCoverageAnalyzer:
    """Analyzes behavioral diffs and existing test coverage to infer missing test requirements."""

    def infer_missing_requirements(
        self,
        behavior_summary: BehaviorChangeSummary,
        coverage_map: dict[str, CoverageLocationResult],
    ) -> list[MissingTestRequirement]:
        """
        Infer a list of missing test requirements for modified/added code.
        """
        requirements: list[MissingTestRequirement] = []

        for change in behavior_summary.changes:
            src_file = change.file_path
            symbol = change.symbol_name
            cov = coverage_map.get(src_file)

            # Check if symbol is already covered in existing tests
            if cov and symbol in cov.covered_symbols:
                # If signature changed, still require boundary / parameter update test
                if change.change_type == "modified_signature":
                    requirements.append(
                        MissingTestRequirement(
                            target_file=src_file,
                            target_symbol=symbol,
                            scenario_name=f"test_{symbol}_new_signature",
                            scenario_type="boundary_condition",
                            description=f"Test updated signature of '{symbol}' with new parameters: {change.parameters_changed}",
                            priority="high",
                        )
                    )
                continue

            # Uncovered added or modified function
            if (
                "function" in change.change_type
                or "signature" in change.change_type
                or "logic" in change.change_type
            ):
                # 1. Happy path requirement
                requirements.append(
                    MissingTestRequirement(
                        target_file=src_file,
                        target_symbol=symbol,
                        scenario_name=f"test_{symbol}_success",
                        scenario_type="happy_path",
                        description=f"Verify happy path execution for '{symbol}' with valid parameters.",
                        priority="high",
                    )
                )

                # 2. Error handling requirement
                requirements.append(
                    MissingTestRequirement(
                        target_file=src_file,
                        target_symbol=symbol,
                        scenario_name=f"test_{symbol}_error_handling",
                        scenario_type="error_handling",
                        description=f"Verify graceful error handling and exception raising for '{symbol}'.",
                        priority="medium",
                    )
                )

        return requirements

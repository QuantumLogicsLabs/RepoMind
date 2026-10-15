"""tests/test_autonomous_test_generator.py

Comprehensive tests for RepoMind Autonomous Test Generation system.
"""

from tools.diff_analyzer import analyze_diffs, analyze_file_change


class TestDiffAnalyzer:
    """Task 1 tests: Diff & Behavioral Change Detection."""

    def test_detect_added_symbol(self):
        old_code = "def existing_fn():\n    pass\n"
        new_code = "def existing_fn():\n    pass\n\ndef new_feature(x, y):\n    return x + y\n"

        changes = analyze_file_change("utils/math_helper.py", old_code, new_code)
        assert len(changes) >= 1

        added = [c for c in changes if c.symbol_name == "new_feature"]
        assert len(added) == 1
        assert added[0].change_type == "added_function"
        assert "x" in added[0].parameters_changed
        assert "y" in added[0].parameters_changed

    def test_detect_modified_signature(self):
        old_code = "def calculate_total(price):\n    return price * 1.1\n"
        new_code = "def calculate_total(price, tax_rate=0.1, discount=0):\n    return price * (1 + tax_rate) - discount\n"

        changes = analyze_file_change("services/billing.py", old_code, new_code)
        modified = [c for c in changes if c.symbol_name == "calculate_total"]

        assert len(modified) == 1
        assert modified[0].change_type == "modified_signature"
        assert modified[0].risk_level == "high"
        assert (
            "tax_rate" in modified[0].parameters_changed
            or "discount" in modified[0].parameters_changed
        )

    def test_analyze_diffs_aggregated_summary(self):
        file_changes = [
            {
                "filename": "api/routes.py",
                "old_content": "def get_status(): return 'ok'",
                "updated_content": "def get_status(): return 'ok'\ndef get_metrics(): return {'cpu': 10}",
                "reason": "Add metrics endpoint",
            }
        ]

        summary = analyze_diffs(file_changes)
        assert "api/routes.py" in summary.modified_files
        assert "get_metrics" in summary.added_symbols
        assert summary.overall_risk in ("medium", "high")


class TestCoverageLocator:
    """Task 2 tests: Locating existing tests associated with affected modules."""

    def test_locate_existing_test_file(self, tmp_path):
        from tools.test_coverage_locator import TestCoverageLocator

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_agent.py").write_text(
            "def test_agent_run():\n    assert True\n", encoding="utf-8"
        )

        locator = TestCoverageLocator(tests_dir=tests_dir)
        found = locator.locate_test_file("agent/executor.py")

        assert found is not None
        assert found.name == "test_agent.py"

    def test_symbol_coverage_detection(self, tmp_path):
        from tools.test_coverage_locator import TestCoverageLocator

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_metrics.py").write_text(
            "def test_record_duration():\n    metrics_collector.record_duration('x', 1)\n",
            encoding="utf-8",
        )

        locator = TestCoverageLocator(tests_dir=tests_dir)
        res = locator.get_coverage("utils/metrics.py", ["record_duration", "uncovered_fn"])

        assert res.test_file_exists is True
        assert "record_duration" in res.covered_symbols
        assert "uncovered_fn" in res.uncovered_symbols


class TestCoverageAnalyzer:
    """Task 3 tests: Inferring missing behavioral coverage."""

    def test_infer_missing_happy_path_and_error_handling(self):
        from agent.coverage_analyzer import BehavioralCoverageAnalyzer
        from tools.diff_analyzer import BehaviorChange, BehaviorChangeSummary
        from tools.test_coverage_locator import CoverageLocationResult

        summary = BehaviorChangeSummary(
            changes=[
                BehaviorChange(
                    file_path="agent/planner.py",
                    symbol_name="generate_sub_plan",
                    change_type="added_function",
                    summary="Added sub plan generator",
                )
            ]
        )
        cov_map = {
            "agent/planner.py": CoverageLocationResult(
                source_file="agent/planner.py",
                associated_test_file="tests/test_agent.py",
                test_file_exists=True,
                uncovered_symbols=["generate_sub_plan"],
            )
        }

        analyzer = BehavioralCoverageAnalyzer()
        reqs = analyzer.infer_missing_requirements(summary, cov_map)

        assert len(reqs) == 2
        types = [r.scenario_type for r in reqs]
        assert "happy_path" in types
        assert "error_handling" in types


class TestGeneratorSchemas:
    """Task 4 tests: Structured Test Case Schemas & Spec Generator."""

    def test_schema_instantiation_and_defaults(self):
        from agent.test_schemas import MockSpec, TestAssertionSpec, TestCaseSpec, TestSuiteSpec

        spec = TestSuiteSpec(
            target_file="agent/executor.py",
            test_file="tests/test_agent.py",
            imports=["import pytest"],
            test_cases=[
                TestCaseSpec(
                    test_name="test_execute_retry",
                    target_symbol="StepExecutor.execute",
                    description="Tests retry when file_changes is empty.",
                    is_async=False,
                    mocks=[MockSpec(target="tool.fn", return_value={})],
                    assertions=[
                        TestAssertionSpec(
                            assertion_type="equal", actual_expr="res.retried", expected_expr="True"
                        )
                    ],
                )
            ],
        )

        assert spec.target_file == "agent/executor.py"
        assert len(spec.test_cases) == 1
        assert spec.test_cases[0].test_name == "test_execute_retry"
        assert spec.test_cases[0].mocks[0].target == "tool.fn"

    def test_fallback_spec_generation(self):
        from agent.coverage_analyzer import MissingTestRequirement
        from agent.test_generator import AutonomousTestGenerator

        generator = AutonomousTestGenerator(llm=None)
        reqs = [
            MissingTestRequirement(
                target_file="utils/metrics.py",
                target_symbol="record_event",
                scenario_name="test_record_event_success",
                scenario_type="happy_path",
                description="Test event recording.",
            )
        ]

        suite_spec = generator.generate_spec(
            target_file="utils/metrics.py",
            test_file="tests/test_metrics.py",
            source_code="def record_event(name): pass",
            requirements=reqs,
        )

        assert suite_spec.target_file == "utils/metrics.py"
        assert len(suite_spec.test_cases) == 1
        assert "record_event" in suite_spec.test_cases[0].target_symbol


class TestImplementer:
    """Task 5 tests: Repository-Conforming Test Implementer."""

    def test_render_suite_to_valid_python_code(self):
        from agent.test_implementer import TestImplementer
        from agent.test_schemas import TestAssertionSpec, TestCaseSpec, TestSuiteSpec

        spec = TestSuiteSpec(
            target_file="agent/planner.py",
            test_file="tests/test_agent.py",
            test_cases=[
                TestCaseSpec(
                    test_name="test_planner_step_cap",
                    target_symbol="TaskPlanner.plan",
                    description="Verify max step capping.",
                    is_async=False,
                    assertions=[
                        TestAssertionSpec(
                            assertion_type="equal",
                            actual_expr="len(plan.steps)",
                            expected_expr="10",
                        )
                    ],
                )
            ],
        )

        implementer = TestImplementer()
        code = implementer.render_suite(spec)

        assert "class TestPlannerAutonomousGenerated:" in code
        assert "def test_planner_step_cap(self):" in code
        assert "assert len(plan.steps) == 10" in code

    def test_merge_into_existing_file(self):
        from agent.test_implementer import TestImplementer

        existing = "def test_existing(): assert True\n"
        new_test = "class TestNew: def test_sub(): assert True"

        implementer = TestImplementer()
        merged = implementer.merge_into_existing_file(existing, new_test)

        assert "test_existing()" in merged
        assert "class TestNew:" in merged


class TestControlledRunner:
    """Task 6 tests: Controlled Subprocess Test Runner."""

    def test_run_passing_test_file(self, tmp_path):
        from tools.controlled_test_runner import ControlledTestRunner

        test_file = tmp_path / "test_sample.py"
        test_file.write_text("def test_dummy(): assert True\n", encoding="utf-8")

        runner = ControlledTestRunner()
        result = runner.run_test_file(test_file)

        assert result.success is True
        assert result.exit_code == 0
        assert result.passed_count >= 1

    def test_run_failing_test_file(self, tmp_path):
        from tools.controlled_test_runner import ControlledTestRunner

        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_failure(): assert 1 == 2\n", encoding="utf-8")

        runner = ControlledTestRunner()
        result = runner.run_test_file(test_file)

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count == 1
        assert "assert 1 == 2" in result.stdout or "assert 1 == 2" in result.error_traceback


class TestRefinerLoop:
    """Task 7 tests: Diagnostic Failure Refinement Loop."""

    def test_diagnose_failure_types(self):
        from agent.test_refiner import AutonomousTestRefiner

        refiner = AutonomousTestRefiner()

        diag_import = refiner.diagnose_failure("ModuleNotFoundError: No module named 'fake_module'")
        assert diag_import.failure_type == "import_error"

        diag_attr = refiner.diagnose_failure("AttributeError: 'Mock' object has no attribute 'foo'")
        assert diag_attr.failure_type == "attribute_error"

        diag_assert = refiner.diagnose_failure("AssertionError: assert 1 == 2")
        assert diag_assert.failure_type == "assertion_error"

    def test_refine_and_fix_missing_imports(self, tmp_path):
        from agent.test_refiner import AutonomousTestRefiner
        from tools.controlled_test_runner import ControlledTestRunner

        test_file = tmp_path / "test_refinement.py"
        # Code missing import pytest
        broken_code = "def test_auto(): assert True\n"

        refiner = AutonomousTestRefiner(runner=ControlledTestRunner())
        _final_code, res = refiner.refine_and_run(str(test_file), broken_code, max_attempts=2)

        assert res.success is True
        assert res.passed_count >= 1


class TestAutonomousChainIntegration:
    """Task 8 tests: End-to-end integration into AgentChain."""

    def test_chain_autonomous_test_generation_trigger(self, tmp_path):
        from unittest.mock import MagicMock

        from agent.chain import AgentChain
        from agent.executor import ExecutorOutput, FileChange, StepExecutionResult

        mock_llm = MagicMock()
        chain = AgentChain(llm=mock_llm, tools=[])

        file_change = FileChange(
            filename="utils/sample.py",
            updated_content="def new_util(): return True",
            reason="Added new utility",
        )
        mock_execution = ExecutorOutput(
            results=[StepExecutionResult(step_id=1, step_task="Add new utility")],
            all_file_changes=[file_change],
        )

        # Execute autonomous test generation
        chain._generate_autonomous_tests(mock_execution)
        # Should complete without error
        assert True

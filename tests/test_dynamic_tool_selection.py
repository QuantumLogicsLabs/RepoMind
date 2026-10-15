from unittest.mock import MagicMock, patch

from agent.executor import (
    PreconditionResult,
    StepExecutor,
    ToolDecision,
    ToolSpec,
)
from agent.planner import Plan, PlanStep
from utils.metrics import metrics_collector


def _make_step() -> PlanStep:
    return PlanStep(
        id=1,
        task="test task",
        target_files=["a.py"],
        target_function="<new>",
        new_logic="n/a",
        expected_output="n/a",
        acceptance_criteria="n/a",
    )


def _dummy_fn(inputs: dict) -> dict:
    return {
        "file_changes": [{"filename": "a.py", "updated_content": "x = 1\n" * 20, "reason": "test"}]
    }


def test_default_precondition_always_passes():
    """A tool with no custom precondition should be usable regardless of step fields."""
    tool = ToolSpec(name="generic", description="d", fn=_dummy_fn)
    step = PlanStep(
        id=1,
        task="t",
        target_files=[],
        target_function="<new>",
        new_logic="n/a",
        expected_output="n/a",
        acceptance_criteria="n/a",
    )
    result = tool.precondition(step, {})
    assert result.ok is True


def test_select_and_validate_tool_falls_back_when_precondition_fails():
    """When the LLM's chosen tool fails its precondition, the executor should
    substitute the configured fallback_tool_name instead of giving up.
    """
    broken = ToolSpec(
        name="broken",
        description="d",
        fn=_dummy_fn,
        precondition=lambda step, ctx: PreconditionResult(ok=False, reason="nope"),
        fallback_tool_name="backup",
    )
    backup = ToolSpec(name="backup", description="d", fn=_dummy_fn)

    executor = StepExecutor(llm=MagicMock(), tools=[broken, backup])
    decision = ToolDecision(tool_name="broken", tool_input={})
    tool, resolved_name, reason = executor._select_and_validate_tool(decision, _make_step(), {})

    assert tool is not None
    assert resolved_name == "backup"
    assert reason == ""


def test_select_and_validate_tool_denies_unpermitted_tool():
    """A tool flagged requires_permission=True must be rejected when its name
    isn't in the executor's allowed_tool_names set.
    """
    gated = ToolSpec(name="dangerous", description="d", fn=_dummy_fn, requires_permission=True)
    executor = StepExecutor(llm=MagicMock(), tools=[gated], allowed_tool_names=set())
    decision = ToolDecision(tool_name="dangerous", tool_input={})
    tool, resolved_name, reason = executor._select_and_validate_tool(decision, _make_step(), {})

    assert tool is None
    assert "permission" in reason.lower() or "no usable tool" in reason.lower()


def test_select_and_validate_tool_allows_permitted_tool():
    """A requires_permission tool IS usable when explicitly named in allowed_tool_names."""
    gated = ToolSpec(name="dangerous", description="d", fn=_dummy_fn, requires_permission=True)
    executor = StepExecutor(llm=MagicMock(), tools=[gated], allowed_tool_names={"dangerous"})
    decision = ToolDecision(tool_name="dangerous", tool_input={})
    tool, resolved_name, reason = executor._select_and_validate_tool(decision, _make_step(), {})

    assert tool is not None
    assert resolved_name == "dangerous"


def test_select_and_validate_tool_returns_none_when_no_fallback_available():
    """If the chosen tool fails and has no fallback_tool_name, selection should
    cleanly fail with a clear reason rather than raising.
    """
    broken = ToolSpec(
        name="broken",
        description="d",
        fn=_dummy_fn,
        precondition=lambda step, ctx: PreconditionResult(ok=False, reason="nope"),
    )
    executor = StepExecutor(llm=MagicMock(), tools=[broken])
    decision = ToolDecision(tool_name="broken", tool_input={})
    tool, resolved_name, reason = executor._select_and_validate_tool(decision, _make_step(), {})

    assert tool is None
    assert reason != ""


def test_execute_records_selection_metrics_for_fallback_and_direct_choice():
    """Running a plan that requires a fallback should be reflected in
    MetricsCollector's selection_accuracy summary.
    """
    metrics_collector.reset()

    broken = ToolSpec(
        name="broken",
        description="d",
        fn=_dummy_fn,
        precondition=lambda step, ctx: PreconditionResult(ok=False, reason="nope"),
        fallback_tool_name="good",
    )
    good = ToolSpec(name="good", description="d", fn=_dummy_fn)

    executor = StepExecutor(llm=MagicMock(), tools=[broken, good])
    plan = Plan(steps=[_make_step()])

    with patch.object(
        executor, "_decide_tool", return_value=ToolDecision(tool_name="broken", tool_input={})
    ):
        executor.execute(plan)

    summary = metrics_collector.get_metrics_summary()
    accuracy = summary["tools"]["selection_accuracy"]

    assert accuracy["total_selections"] == 1
    assert accuracy["fallback_used"] == 1
    assert accuracy["first_choice_accepted"] == 0
    assert accuracy["first_choice_accuracy_pct"] == 0.0


def test_execute_uses_resolved_tool_name_in_step_result():
    """The StepExecutionResult.tool_name should reflect the tool that
    actually ran, not the LLM's original (possibly rejected) choice.
    """
    broken = ToolSpec(
        name="broken",
        description="d",
        fn=_dummy_fn,
        precondition=lambda step, ctx: PreconditionResult(ok=False, reason="nope"),
        fallback_tool_name="good",
    )
    good = ToolSpec(name="good", description="d", fn=_dummy_fn)

    executor = StepExecutor(llm=MagicMock(), tools=[broken, good])
    plan = Plan(steps=[_make_step()])

    with patch.object(
        executor, "_decide_tool", return_value=ToolDecision(tool_name="broken", tool_input={})
    ):
        output = executor.execute(plan)

    assert output.results[0].tool_name == "good"
    assert len(output.all_file_changes) == 1

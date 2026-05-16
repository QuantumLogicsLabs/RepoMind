from unittest.mock import MagicMock, patch
from agent.planner import TaskPlanner, Plan, PlanStep
from agent.executor import StepExecutor, ToolSpec, ToolDecision, ExecutorOutput, StepExecutionResult
from agent.chain import AgentChain
from agent.memory import MemoryManager

def test_planner_creates_plan():
    planner = TaskPlanner(llm=MagicMock())
    mock_plan = Plan(steps=[
        PlanStep(id=1, task="Create a new python file", target_function="main", new_logic="print('hello')", expected_output="File exists")
    ])
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = mock_plan
    with patch.object(planner, 'build_chain', return_value=mock_chain):
        result = planner.plan(instruction="Make a python file", context_messages=[])
    assert len(result.steps) == 1
    assert result.steps[0].task == "Create a new python file"

def test_executor_runs_tools():
    def fake_tool_fn(inputs):
        return {
            "file_changes": [
                {"filename": "test.txt", "updated_content": "Hello World", "reason": "Testing tool"}
            ],
            "notes": "File updated successfully"
        }
    fake_tool = ToolSpec(name="fake_file_tool", description="A tool that edits files", fn=fake_tool_fn)
    executor = StepExecutor(llm=MagicMock(), tools=[fake_tool])
    dummy_plan = Plan(steps=[
        PlanStep(id=1, task="Write hello world", target_function="write", new_logic="write file", expected_output="Done")
    ])
    mock_decision = ToolDecision(tool_name="fake_file_tool", tool_input={"filename": "test.txt"})
    with patch.object(executor, '_decide_tool', return_value=mock_decision):
        result = executor.execute(dummy_plan)
    assert len(result.results) == 1
    assert result.results[0].tool_name == "fake_file_tool"
    assert len(result.all_file_changes) == 1
    assert result.all_file_changes[0].filename == "test.txt"
    assert result.all_file_changes[0].updated_content == "Hello World"

def test_chain_processes_request():
    chain = AgentChain(llm=MagicMock(), tools=[])
    dummy_plan = Plan(steps=[
        PlanStep(id=1, task="Dummy step", target_function="dummy", new_logic="pass", expected_output="Done")
    ])
    dummy_execution = ExecutorOutput(
        results=[StepExecutionResult(step_id=1, step_task="Dummy step", tool_name="noop", tool_input={})],
        all_file_changes=[]
    )
    with patch.object(chain.planner, 'plan', return_value=dummy_plan):
        with patch.object(chain.executor, 'execute', return_value=dummy_execution):
            result = chain.run(session_id="session_123", instruction="Do something")
    assert result.session_id == "session_123"
    assert result.plan == dummy_plan
    assert result.execution == dummy_execution
    context = chain.memory.get_context_messages("session_123")
    assert len(context) == 2
    assert context[0].type == "human"
    assert context[1].type == "ai"

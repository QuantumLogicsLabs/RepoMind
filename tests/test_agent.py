import pytest
from unittest.mock import MagicMock, patch

from agent.planner import TaskPlanner, Plan, PlanStep
from agent.executor import StepExecutor, ToolSpec, ToolDecision, ExecutorOutput, StepExecutionResult, FileChange
from agent.chain import AgentChain, ChainResult
from agent.memory import MemoryManager

def test_planner_creates_plan():
    """Test that the planner correctly breaks down a prompt into a structured Plan."""
    # 1. Setup the planner with a basic mock LLM
    planner = TaskPlanner(llm=MagicMock())
    
    # 2. Tell the fake AI exactly what to output when called
    mock_plan = Plan(steps=[
        PlanStep(id=1, task="Create a new python file", target_files=["main.py"], acceptance_criteria="File exists")
    ])
    
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = mock_plan

    # 3. Patch the build_chain method to skip LangChain's complex logic
    with patch.object(planner, 'build_chain', return_value=mock_chain):
        result = planner.plan(instruction="Make a python file", context_messages=[])

    # 4. Verify the planner didn't crash and returned our expected plan
    assert len(result.steps) == 1
    assert result.steps[0].task == "Create a new python file"


def test_executor_runs_tools():
    """Test that the executor correctly decides on a tool and captures file changes."""
    # 1. Create a fake tool function that pretends to edit a file
    def fake_tool_fn(inputs):
        return {
            "file_changes": [
                {"filename": "test.txt", "updated_content": "Hello World", "reason": "Testing tool"}
            ],
            "notes": "File updated successfully"
        }
    
    fake_tool = ToolSpec(name="fake_file_tool", description="A tool that edits files", fn=fake_tool_fn)

    # 2. Setup the Executor
    executor = StepExecutor(llm=MagicMock(), tools=[fake_tool])
    dummy_plan = Plan(steps=[
        PlanStep(id=1, task="Write hello world", target_files=["test.txt"], acceptance_criteria="Done")
    ])

    # 3. Create a fake decision
    mock_decision = ToolDecision(tool_name="fake_file_tool", tool_input={"filename": "test.txt"})

    # 4. Patch the _decide_tool method directly so we skip the LLM call
    with patch.object(executor, '_decide_tool', return_value=mock_decision):
        result = executor.execute(dummy_plan)

    # 5. Verify the executor caught the file change
    assert len(result.results) == 1
    assert result.results[0].tool_name == "fake_file_tool"
    assert len(result.all_file_changes) == 1
    assert result.all_file_changes[0].filename == "test.txt"
    assert result.all_file_changes[0].updated_content == "Hello World"


def test_chain_processes_request():

    
    """Test the full AgentChain from memory to summary."""
    # Setup chain with dummy LLM
    chain = AgentChain(llm=MagicMock(), tools=[])

    # For the full chain, we can patch (mock) the Planner and Executor directly
    # so we don't have to deal with complex LLM logic here.
    dummy_plan = Plan(steps=[
        PlanStep(id=1, task="Dummy step", target_files=[], acceptance_criteria="Done")
    ])
    
    dummy_execution = ExecutorOutput(
        results=[StepExecutionResult(step_id=1, step_task="Dummy step", tool_name="noop", tool_input={})],
        all_file_changes=[]
    )

    # Force the chain's planner and executor to return our dummy data
    with patch.object(chain.planner, 'plan', return_value=dummy_plan):
        with patch.object(chain.executor, 'execute', return_value=dummy_execution):
            result = chain.run(session_id="session_123", instruction="Do something")

    # Verify the chain packaged the results correctly
    assert result.session_id == "session_123"
    assert result.plan == dummy_plan
    assert result.execution == dummy_execution

    # Verify the memory manager saved the context (User message + AI summary)
    context = chain.memory.get_context_messages("session_123")
    assert len(context) == 2 
    assert context[0].type == "human"
    assert context[1].type == "ai"
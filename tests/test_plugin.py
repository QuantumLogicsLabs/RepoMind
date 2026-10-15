"""tests/test_plugin.py

Unit and integration tests for RepoMind Plugin System.
"""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent.chain import AgentChain
from agent.executor import ToolSpec
from agent.planner import TaskPlanner
from agent.plugin import BasePlugin, PluginManager, PluginMetadata


class SampleLinterPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="sample_linter",
            version="1.1.0",
            description="Sample linter for unit tests",
            author="Unit Test",
        )

    def get_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="run_sample_linter",
                description="Runs sample linter tool",
                fn=lambda inputs: {"notes": "Linter executed cleanly", "file_changes": []},
            )
        ]

    def get_planner_instructions(self) -> list[str]:
        return ["Always invoke run_sample_linter after editing python files."]

    def get_hooks(self) -> dict[str, Any]:
        return {"pre_step": lambda step, ctx: None}


def test_base_plugin_metadata():
    plugin = SampleLinterPlugin()
    assert plugin.name == "sample_linter"
    assert plugin.metadata.version == "1.1.0"
    assert plugin.metadata.description == "Sample linter for unit tests"
    assert not plugin._is_initialized

    plugin.initialize({"env": "test"})
    assert plugin._is_initialized

    plugin.shutdown()
    assert not plugin._is_initialized


def test_plugin_manager_registration():
    pm = PluginManager()
    plugin = SampleLinterPlugin()

    pm.register_plugin(plugin)
    assert len(pm.get_plugins()) == 1
    assert pm.get_plugin("sample_linter") is plugin

    tools = pm.get_all_tools()
    assert len(tools) == 1
    assert tools[0].name == "run_sample_linter"

    instructions = pm.get_all_planner_instructions()
    assert len(instructions) == 1
    assert "run_sample_linter" in instructions[0]

    hooks = pm.get_all_hooks()
    assert "pre_step" in hooks

    pm.unregister_plugin("sample_linter")
    assert len(pm.get_plugins()) == 0


def test_disabled_plugin_registration():
    pm = PluginManager()

    class DisabledPlugin(BasePlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(name="disabled_plugin", enabled=False)

    plugin = DisabledPlugin()
    pm.register_plugin(plugin)
    assert len(pm.get_plugins()) == 0


def test_load_plugin_from_path():
    pm = PluginManager()

    plugin_code = """
from agent.plugin import BasePlugin, PluginMetadata
from agent.executor import ToolSpec

class DynamicFilePlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="dynamic_file_plugin", version="2.0.0")

    def get_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name="dynamic_tool", description="Dynamic", fn=lambda x: {})]
"""

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / "custom_plugin.py"
        file_path.write_text(plugin_code, encoding="utf-8")

        loaded = pm.load_plugin_from_path(file_path)
        assert len(loaded) == 1
        assert loaded[0].name == "dynamic_file_plugin"
        assert pm.get_plugin("dynamic_file_plugin") is not None
        assert len(pm.get_all_tools()) == 1
        assert pm.get_all_tools()[0].name == "dynamic_tool"


def test_discover_plugins_directory():
    pm = PluginManager()

    plugin_code = """
from agent.plugin import BasePlugin, PluginMetadata

class DiscoveredPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="discovered_plugin")
"""

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / "plugin_one.py"
        file_path.write_text(plugin_code, encoding="utf-8")

        discovered = pm.discover_plugins(tmp_dir)
        assert len(discovered) == 1
        assert discovered[0].name == "discovered_plugin"


def test_task_planner_extra_instructions():
    llm = MagicMock()
    extra = ["Custom instruction line 1", "Custom instruction line 2"]

    planner = TaskPlanner(llm=llm, extra_instructions=extra)
    # Check that system message prompt text contains extra instructions
    system_prompt = planner.prompt.messages[0].prompt.template
    assert "ADDITIONAL PLUGIN INSTRUCTIONS:" in system_prompt
    assert "Custom instruction line 1" in system_prompt
    assert "Custom instruction line 2" in system_prompt


def test_agent_chain_plugin_integration():
    pm = PluginManager()
    plugin = SampleLinterPlugin()
    pm.register_plugin(plugin)

    llm = MagicMock()
    chain = AgentChain(llm=llm, tools=[], plugin_mgr=pm)

    # StepExecutor should have the plugin tool
    assert "run_sample_linter" in chain.executor.tools_by_name
    # TaskPlanner should have the plugin planner instruction
    assert len(chain.planner.extra_instructions) == 1
    assert "run_sample_linter" in chain.planner.extra_instructions[0]


def test_invalid_plugin_registration_error():
    pm = PluginManager()
    with pytest.raises(TypeError):
        pm.register_plugin("not_a_plugin")

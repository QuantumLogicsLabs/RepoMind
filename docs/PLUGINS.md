# 🔌 RepoMind Plugin Development Guide

RepoMind supports a modular **Plugin System** that allows developers to extend the agent with custom tools (such as linters, code formatters, and test runners), custom planner rules, and execution lifecycle hooks.

---

## 🏗️ Core Architecture

The plugin system consists of three main components:

1. **`BasePlugin`**: The abstract base class that all custom plugins inherit from.
2. **`PluginMetadata`**: Defines plugin metadata (name, version, description, author, enabled status).
3. **`PluginManager`**: Discovers, loads, registers, and manages plugin lifecycles, aggregating tools and planner rules.

---

## 🚀 Creating a Custom Plugin

To build a plugin:
1. Subclass `agent.plugin.BasePlugin`.
2. Define the `@property metadata`.
3. Override `get_tools()` to return custom `ToolSpec` instances.
4. (Optional) Override `get_planner_instructions()` to guide the `TaskPlanner` on when to call your tool.

### Example: Code Linter Plugin

```python
# plugins/linter_plugin.py

import subprocess
from typing import Any
from agent.plugin import BasePlugin, PluginMetadata
from agent.executor import ToolSpec


class LinterPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="linter_plugin",
            version="1.0.0",
            description="Runs ruff linter on modified files to verify code quality.",
            author="RepoMind Developer",
        )

    def get_planner_instructions(self) -> list[str]:
        return [
            "Use tool 'run_linter' whenever Python files are created or modified to verify syntax and formatting."
        ]

    def get_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="run_linter",
                description="Runs ruff linter on a specified python file path.",
                fn=self._run_linter,
            )
        ]

    def _run_linter(self, inputs: dict[str, Any]) -> dict[str, Any]:
        filename = inputs.get("filename", "")
        if not filename:
            return {"notes": "Linter skipped: no filename provided."}

        # Run ruff check
        res = subprocess.run(
            ["ruff", "check", filename],
            capture_output=True,
            text=True,
        )
        status = "PASSED" if res.returncode == 0 else "FAILED"
        return {
            "notes": f"Linter status for {filename}: {status}.\nOutput:\n{res.stdout or res.stderr}",
            "file_changes": [],
        }
```

---

## ⚙️ Registration & Configuration

Plugins can be loaded in three ways:

### 1. Automatic Directory Discovery
Place your plugin `.py` file inside the configured plugins directory (`plugins/` by default). RepoMind automatically scans and registers all valid `BasePlugin` subclasses on startup.

### 2. Configuration Settings (`.env`)
Enable specific plugins or files in `.env` / `Settings`:

```env
PLUGINS_DIR=plugins
ENABLED_PLUGINS=plugins/linter_plugin.py,my_custom_module
```

### 3. Programmatic Registration
Register plugins manually in code using `plugin_manager`:

```python
from agent.plugin import plugin_manager
from plugins.linter_plugin import LinterPlugin

# Register instance
plugin_manager.register_plugin(LinterPlugin())
```

---

## 🔄 Execution Hooks

Plugins can register lifecycle hooks for pre-step and post-step execution:

```python
def get_hooks(self) -> dict[str, Callable]:
    return {
        "pre_step": self.on_pre_step,
        "post_step": self.on_post_step,
    }

def on_pre_step(self, step, context):
    print(f"Starting step: {step.task}")

def on_post_step(self, step_result, context):
    print(f"Finished step: {step_result.step_task}")
```

---

## 🧪 Testing Plugins

Test your custom plugins using `pytest`:

```python
from agent.plugin import PluginManager
from plugins.linter_plugin import LinterPlugin

def test_linter_plugin_registration():
    pm = PluginManager()
    plugin = LinterPlugin()
    pm.register_plugin(plugin)

    assert len(pm.get_plugins()) == 1
    assert len(pm.get_all_tools()) == 1
    assert pm.get_all_tools()[0].name == "run_linter"
```

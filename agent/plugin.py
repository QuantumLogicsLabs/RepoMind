"""agent/plugin.py

Plugin System Interface & Manager for RepoMind.

Enables developers to extend RepoMind with custom tools (e.g. linters, formatters,
test runners), planner instructions, and lifecycle hooks.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.executor import ToolSpec
from utils.logging import get_logger

logger = get_logger("agent.plugin")


@dataclass
class PluginMetadata:
    """Metadata describing a RepoMind plugin."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    enabled: bool = True


class BasePlugin(ABC):
    """
    Abstract base class for all RepoMind plugins.

    Custom plugins inherit from BasePlugin to register tools, planner prompt
    rules, and execution lifecycle hooks.

    Example:
        class LinterPlugin(BasePlugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="linter_plugin",
                    version="1.0.0",
                    description="Runs ruff linter on modified files.",
                )

            def get_tools(self) -> list[ToolSpec]:
                return [
                    ToolSpec(
                        name="run_linter",
                        description="Run ruff linter on target python file",
                        fn=self._run_linter,
                    )
                ]
    """

    def __init__(self) -> None:
        self._is_initialized: bool = False

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata (name, version, description, author)."""
        pass

    @property
    def name(self) -> str:
        """Convenience property to access plugin name."""
        return self.metadata.name

    def initialize(self, context: dict[str, Any] | None = None) -> None:
        """
        Lifecycle hook called when the plugin is registered.

        Args:
            context: Optional dictionary containing configuration or runtime state.
        """
        self._is_initialized = True
        logger.info(
            "Plugin '%s' (v%s) initialized.",
            self.metadata.name,
            self.metadata.version,
            extra={"event": "plugin_initialized", "plugin": self.metadata.name},
        )

    def get_tools(self) -> list[ToolSpec]:
        """
        Return custom ToolSpec instances provided by this plugin.

        Override this method to expose custom agent tools to StepExecutor.
        """
        return []

    def get_planner_instructions(self) -> list[str]:
        """
        Return extra instructions/guidance strings to inject into TaskPlanner.

        Override this method to teach the planner when and how to select
        tools provided by this plugin.
        """
        return []

    def get_hooks(self) -> dict[str, Callable[..., Any]]:
        """
        Return optional pre/post execution lifecycle hooks.

        Supported hook names:
        - "pre_step": fn(step, context)
        - "post_step": fn(step_result, context)
        """
        return {}

    def shutdown(self) -> None:
        """Lifecycle hook called when the plugin is unregistered or app stops."""
        self._is_initialized = False
        logger.info(
            "Plugin '%s' shut down.",
            self.metadata.name,
            extra={"event": "plugin_shutdown", "plugin": self.metadata.name},
        )


class PluginManager:
    """
    Manages plugin registration, dynamic tool loading, and planner extensions.

    Discovers plugins from Python modules, script files, or directories and
    aggregates custom ToolSpec tools and planner instructions.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}

    def register_plugin(self, plugin: BasePlugin, context: dict[str, Any] | None = None) -> None:
        """
        Register and initialize a plugin instance.

        Args:
            plugin: BasePlugin subclass instance.
            context: Optional runtime context passed to initialize().
        """
        if not isinstance(plugin, BasePlugin):
            raise TypeError(f"Object {plugin} must be an instance of BasePlugin.")

        name = plugin.name
        if not name:
            raise ValueError("Plugin metadata must specify a non-empty name.")

        if name in self._plugins:
            logger.warning("Plugin '%s' is already registered. Overwriting.", name)
            self.unregister_plugin(name)

        if not plugin.metadata.enabled:
            logger.info("Plugin '%s' is disabled. Skipping registration.", name)
            return

        plugin.initialize(context=context)
        self._plugins[name] = plugin
        logger.info("Successfully registered plugin '%s'.", name)

    def unregister_plugin(self, name: str) -> None:
        """Unregister and shut down a plugin by name."""
        if name in self._plugins:
            plugin = self._plugins.pop(name)
            try:
                plugin.shutdown()
            except Exception as e:
                logger.error("Error shutting down plugin '%s': %e", name, exc_info=e)

    def clear(self) -> None:
        """Unregister all plugins."""
        names = list(self._plugins.keys())
        for name in names:
            self.unregister_plugin(name)

    def get_plugin(self, name: str) -> BasePlugin | None:
        """Get registered plugin by name."""
        return self._plugins.get(name)

    def get_plugins(self) -> list[BasePlugin]:
        """Return list of all currently registered plugins."""
        return list(self._plugins.values())

    def load_plugin_from_path(
        self, file_path: str | Path, context: dict[str, Any] | None = None
    ) -> list[BasePlugin]:
        """
        Dynamically load plugins from a Python file path.

        Inspects the module for non-abstract BasePlugin subclasses, instantiates
        and registers them.

        Returns:
            List of registered BasePlugin instances.
        """
        path = Path(file_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Plugin file not found: {path}")

        module_name = f"repomind_dynamic_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for file: {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        loaded_plugins: list[BasePlugin] = []
        for obj in module.__dict__.values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BasePlugin)
                and obj is not BasePlugin
                and not inspect.isabstract(obj)
            ):
                instance = obj()
                self.register_plugin(instance, context=context)
                loaded_plugins.append(instance)

        return loaded_plugins

    def load_plugin_by_name(
        self, module_name: str, context: dict[str, Any] | None = None
    ) -> list[BasePlugin]:
        """
        Dynamically load plugins from an importable Python module name.

        Returns:
            List of registered BasePlugin instances.
        """
        module = importlib.import_module(module_name)
        loaded_plugins: list[BasePlugin] = []
        for obj in module.__dict__.values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BasePlugin)
                and obj is not BasePlugin
                and not inspect.isabstract(obj)
            ):
                instance = obj()
                self.register_plugin(instance, context=context)
                loaded_plugins.append(instance)

        return loaded_plugins

    def discover_plugins(
        self, plugin_dir: str | Path, context: dict[str, Any] | None = None
    ) -> list[BasePlugin]:
        """
        Scan a directory for `.py` plugin files and load them.

        Returns:
            List of all discovered and registered BasePlugin instances.
        """
        directory = Path(plugin_dir).resolve()
        if not directory.exists() or not directory.is_dir():
            logger.warning("Plugin directory '%s' does not exist.", directory)
            return []

        discovered: list[BasePlugin] = []
        for py_file in directory.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                plugins = self.load_plugin_from_path(py_file, context=context)
                discovered.extend(plugins)
            except Exception as e:
                logger.error("Failed to load plugin from file '%s': %s", py_file, e, exc_info=e)

        return discovered

    def get_all_tools(self) -> list[ToolSpec]:
        """
        Aggregate custom ToolSpec tools from all registered plugins.
        """
        tools: list[ToolSpec] = []
        for plugin in self._plugins.values():
            try:
                plugin_tools = plugin.get_tools()
                tools.extend(plugin_tools)
            except Exception as e:
                logger.error(
                    "Error fetching tools from plugin '%s': %s", plugin.name, e, exc_info=e
                )
        return tools

    def get_all_planner_instructions(self) -> list[str]:
        """
        Aggregate planner instruction strings from all registered plugins.
        """
        instructions: list[str] = []
        for plugin in self._plugins.values():
            try:
                plugin_instructions = plugin.get_planner_instructions()
                instructions.extend(plugin_instructions)
            except Exception as e:
                logger.error(
                    "Error fetching planner instructions from plugin '%s': %s",
                    plugin.name,
                    e,
                    exc_info=e,
                )
        return instructions

    def get_all_hooks(self) -> dict[str, list[Callable[..., Any]]]:
        """
        Aggregate pre/post step lifecycle hooks from all registered plugins.
        """
        aggregated: dict[str, list[Callable[..., Any]]] = {}
        for plugin in self._plugins.values():
            try:
                hooks = plugin.get_hooks()
                for hook_name, fn in hooks.items():
                    aggregated.setdefault(hook_name, []).append(fn)
            except Exception as e:
                logger.error(
                    "Error fetching hooks from plugin '%s': %s", plugin.name, e, exc_info=e
                )
        return aggregated


# Global PluginManager instance for application-wide registration
plugin_manager = PluginManager()

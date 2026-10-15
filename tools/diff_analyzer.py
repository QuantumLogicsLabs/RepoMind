"""tools/diff_analyzer.py

Analyzes code modifications and diffs to infer behavioral changes,
modified/added symbols, and risk indicators for autonomous test generation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BehaviorChange:
    """Represents a single behavioral change detected in a symbol or file."""

    file_path: str
    symbol_name: str
    change_type: str  # "added_function", "modified_function", "modified_class", etc.
    summary: str
    parameters_changed: list[str] = field(default_factory=list)
    return_type_changed: bool = False
    branch_conditions_added: bool = False
    risk_level: str = "low"  # "low", "medium", "high"


@dataclass
class BehaviorChangeSummary:
    """Aggregated summary of behavioral changes across all modified files."""

    changes: list[BehaviorChange] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    modified_symbols: list[str] = field(default_factory=list)
    added_symbols: list[str] = field(default_factory=list)
    overall_risk: str = "low"

    def get_by_file(self, file_path: str) -> list[BehaviorChange]:
        return [c for c in self.changes if c.file_path == file_path]


def _extract_ast_symbols(code: str) -> dict[str, dict[str, Any]]:
    """Extract top-level and class functions with their arg names using AST."""
    symbols: dict[str, dict[str, Any]] = {}
    if not code or not code.strip():
        return symbols

    try:
        tree = ast.parse(code)
    except Exception:
        return symbols

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [arg.arg for arg in node.args.args if arg.arg != "self"]
            symbols[node.name] = {
                "name": node.name,
                "args": args,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "type": "function",
            }
        elif isinstance(node, ast.ClassDef):
            symbols[node.name] = {
                "name": node.name,
                "args": [],
                "is_async": False,
                "type": "class",
            }

    return symbols


def analyze_file_change(
    filename: str,
    old_content: str,
    new_content: str,
    reason: str = "",
) -> list[BehaviorChange]:
    """Analyze old vs new file content to detect symbol-level behavioral changes."""
    changes: list[BehaviorChange] = []
    old_symbols = _extract_ast_symbols(old_content)
    new_symbols = _extract_ast_symbols(new_content)

    # Detect added symbols
    for name, info in new_symbols.items():
        if name not in old_symbols:
            risk = "medium" if info["type"] == "function" else "low"
            changes.append(
                BehaviorChange(
                    file_path=filename,
                    symbol_name=name,
                    change_type=f"added_{info['type']}",
                    summary=f"Added new {info['type']} '{name}' ({'async' if info.get('is_async') else 'sync'})",
                    parameters_changed=info["args"],
                    risk_level=risk,
                )
            )

    # Detect modified symbols
    for name, old_info in old_symbols.items():
        if name in new_symbols:
            new_info = new_symbols[name]
            param_diff = list(set(new_info["args"]) - set(old_info["args"]))

            # Check if logic or params changed
            if param_diff or old_info["args"] != new_info["args"]:
                changes.append(
                    BehaviorChange(
                        file_path=filename,
                        symbol_name=name,
                        change_type="modified_signature",
                        summary=f"Modified parameters for '{name}': added {param_diff}",
                        parameters_changed=param_diff,
                        risk_level="high" if param_diff else "medium",
                    )
                )
            else:
                # Default modified logic
                changes.append(
                    BehaviorChange(
                        file_path=filename,
                        symbol_name=name,
                        change_type="modified_logic",
                        summary=f"Modified internal logic for '{name}'",
                        risk_level="medium",
                    )
                )

    # Fallback if AST couldn't parse or no symbol diff found
    if not changes:
        changes.append(
            BehaviorChange(
                file_path=filename,
                symbol_name=filename,
                change_type="modified_file",
                summary=reason or f"Updated file content of {filename}",
                risk_level="low",
            )
        )

    return changes


def analyze_diffs(file_changes: list[dict[str, Any]] | list[Any]) -> BehaviorChangeSummary:
    """
    Analyze multiple file changes to generate an aggregated BehaviorChangeSummary.

    Args:
        file_changes: List of dicts or objects with 'filename', 'updated_content', 'old_content', 'reason'.

    Returns:
        BehaviorChangeSummary object.
    """
    summary = BehaviorChangeSummary()

    for item in file_changes:
        if hasattr(item, "filename"):
            filename = item.filename
            new_content = getattr(item, "updated_content", "")
            old_content = getattr(item, "old_content", "")
            reason = getattr(item, "reason", "")
        else:
            filename = item.get("filename", "")
            new_content = item.get("updated_content", "")
            old_content = item.get("old_content", "")
            reason = item.get("reason", "")

        if not filename:
            continue

        summary.modified_files.append(filename)
        file_behaviors = analyze_file_change(filename, old_content, new_content, reason)
        summary.changes.extend(file_behaviors)

        for c in file_behaviors:
            if "added" in c.change_type:
                summary.added_symbols.append(c.symbol_name)
            else:
                summary.modified_symbols.append(c.symbol_name)

    # Determine overall risk
    if any(c.risk_level == "high" for c in summary.changes):
        summary.overall_risk = "high"
    elif any(c.risk_level == "medium" for c in summary.changes):
        summary.overall_risk = "medium"
    else:
        summary.overall_risk = "low"

    return summary

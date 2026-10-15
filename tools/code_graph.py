"""
tools/code_graph.py

Builds a structural knowledge graph of a Python repository: functions,
classes, and files as nodes; imports, calls, and inheritance as edges.

"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Literal

EntityType = Literal["file", "function", "class", "method"]
EdgeType = Literal["imports", "calls", "inherits", "defines", "references"]


@dataclass
class GraphNode:
    """One entity in the code graph: a file, function, class, or method."""

    id: str  # unique, e.g. "agent/chain.py::AgentChain.run"
    type: EntityType
    name: str  # short name, e.g. "run"
    file_path: str
    line_number: int
    end_line_number: int | None = None
    parent_id: str | None = None  # e.g. a method's parent class id


@dataclass
class GraphEdge:
    """One relationship between two entities in the code graph."""

    from_id: str
    to_id: str
    type: EdgeType


@dataclass
class CodeGraph:
    """The full graph: all nodes and edges for a parsed repository."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, from_id: str, to_id: str, edge_type: EdgeType) -> None:
        self.edges.append(GraphEdge(from_id=from_id, to_id=to_id, type=edge_type))


class _FileEntityExtractor(ast.NodeVisitor):
    """
    Walks one file's AST and extracts function/class/method nodes, plus
    "calls" and "inherits" edges. Unresolved call targets (names that
    aren't locally defined, e.g. calls into other files or third-party
    libraries) are still recorded as edges pointing at a best-effort
    symbol id — resolution across files happens later in build_code_graph.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.nodes: list[GraphNode] = []
        self.edges: list[GraphEdge] = []
        self._scope_stack: list[str] = []  # stack of enclosing entity ids

    def _current_scope_id(self) -> str:
        return self._scope_stack[-1] if self._scope_stack else self.file_path

    def _make_id(self, name: str) -> str:
        scope = self._current_scope_id()
        if scope == self.file_path:
            return f"{self.file_path}::{name}"
        return f"{scope}.{name}"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_id = self._make_id(node.name)
        self.nodes.append(
            GraphNode(
                id=class_id,
                type="class",
                name=node.name,
                file_path=self.file_path,
                line_number=node.lineno,
                end_line_number=getattr(node, "end_lineno", None),
                parent_id=self._current_scope_id() if self._scope_stack else self.file_path,
            )
        )
        self.edges.append(GraphEdge(from_id=self.file_path, to_id=class_id, type="defines"))

        # Base classes -> "inherits" edges. Best-effort name resolution;
        # cross-file resolution happens later in build_code_graph.
        for base in node.bases:
            base_name = self._expr_to_name(base)
            if base_name:
                self.edges.append(GraphEdge(from_id=class_id, to_id=base_name, type="inherits"))

        self._scope_stack.append(class_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_like(node)

    def _visit_function_like(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_method = (
            bool(self._scope_stack)
            and self.nodes
            and any(n.id == self._scope_stack[-1] and n.type == "class" for n in self.nodes)
        )
        func_id = self._make_id(node.name)
        func_type: EntityType = "method" if is_method else "function"

        self.nodes.append(
            GraphNode(
                id=func_id,
                type=func_type,
                name=node.name,
                file_path=self.file_path,
                line_number=node.lineno,
                end_line_number=getattr(node, "end_lineno", None),
                parent_id=self._current_scope_id(),
            )
        )
        self.edges.append(
            GraphEdge(from_id=self._current_scope_id(), to_id=func_id, type="defines")
        )

        self._scope_stack.append(func_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        callee_name = self._expr_to_name(node.func)
        if callee_name and self._scope_stack:
            caller_id = self._scope_stack[-1]
            self.edges.append(GraphEdge(from_id=caller_id, to_id=callee_name, type="calls"))
        self.generic_visit(node)

    @staticmethod
    def _expr_to_name(expr: ast.expr) -> str | None:
        """Best-effort extraction of a readable name from a call/base-class expression.

        Handles plain names (`foo`), attribute access (`self.foo`, `module.Class`),
        and returns None for anything more complex (e.g. a call result being called).
        """
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            base = _FileEntityExtractor._expr_to_name(expr.value)
            return f"{base}.{expr.attr}" if base else expr.attr
        return None


def extract_file_entities(content: str, file_path: str) -> tuple[list[GraphNode], list[GraphEdge]]:
    """
    Parse one file's source and return the functions/classes/methods it
    defines, plus the "calls"/"inherits"/"defines" edges found within it.

    Returns ([], []) for files with syntax errors, matching the tolerant
    behavior of tools/code_parser.py's extract_python_imports.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [], []

    extractor = _FileEntityExtractor(file_path)
    extractor.visit(tree)
    return extractor.nodes, extractor.edges


def build_code_graph(files_by_path: dict[str, str]) -> CodeGraph:
    """
    Build a full repository code graph from a {file_path: content} mapping

    Combines per-file entity extraction with the existing file-level import
    graph (tools.code_parser.build_import_graph), and resolves "calls" and
    "inherits" edges against known node ids where possible.
    """
    from tools.code_parser import build_import_graph

    graph = CodeGraph()

    # 1. Add a node for every file, and extract its functions/classes/methods.
    for file_path, content in files_by_path.items():
        if not file_path.endswith(".py"):
            continue

        graph.add_node(
            GraphNode(id=file_path, type="file", name=file_path, file_path=file_path, line_number=1)
        )

        nodes, edges = extract_file_entities(content, file_path)
        for node in nodes:
            graph.add_node(node)
        for edge in edges:
            graph.edges.append(edge)

    # 2. Resolve "calls" and "inherits" edges against real node ids where
    #    possible. A call/base-class name like "foo" or "self.foo" is
    #    unqualified; we try to match it against known function/class/method
    #    names within the graph. Ambiguous matches are resolved to the first
    #    match found — this is a best-effort static resolution, not a full
    #    type-aware resolver (that would require import-level tracing per call
    #    site, out of scope for this pass).
    name_to_ids: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        if node.type in ("function", "class", "method"):
            name_to_ids.setdefault(node.name, []).append(node.id)

    resolved_edges: list[GraphEdge] = []
    for edge in graph.edges:
        if edge.type in ("calls", "inherits") and edge.to_id not in graph.nodes:
            # edge.to_id is currently a raw name like "foo" or "self.foo" —
            # try the last dotted segment against known symbol names.
            short_name = edge.to_id.split(".")[-1]
            candidates = name_to_ids.get(short_name)
            if candidates:
                resolved_edges.append(
                    GraphEdge(from_id=edge.from_id, to_id=candidates[0], type=edge.type)
                )
            # If unresolved (e.g. a builtin, stdlib, or third-party call),
            # the edge is dropped rather than kept pointing at a fake node —
            # this keeps get_callers()/get_class_hierarchy() results accurate.
        else:
            resolved_edges.append(edge)

    graph.edges = resolved_edges

    # 3. Layer in file-level import edges from the existing Task 6 graph,
    #    so file-to-file "imports" relationships are part of the same graph.
    import_graph = build_import_graph(files_by_path)
    path_by_module: dict[str, str] = {}
    for file_path in files_by_path:
        if file_path.endswith(".py"):
            normalized = file_path.replace("\\", "/")[: -len(".py")].replace("/", ".")
            path_by_module[normalized] = file_path

    for file_path, imported_modules in import_graph.items():
        for module in imported_modules:
            target_file = path_by_module.get(module)
            if target_file:
                graph.add_edge(file_path, target_file, "imports")

    return graph


def get_callers(graph: CodeGraph, symbol_id: str) -> list[str]:
    """Return the ids of every function/method that calls the given symbol."""
    return sorted({e.from_id for e in graph.edges if e.to_id == symbol_id and e.type == "calls"})


def get_callees(graph: CodeGraph, symbol_id: str) -> list[str]:
    """Return the ids of every function/method the given symbol calls."""
    return sorted({e.to_id for e in graph.edges if e.from_id == symbol_id and e.type == "calls"})


def get_class_hierarchy(graph: CodeGraph, class_id: str) -> dict[str, list[str]]:
    """Return the direct base classes and direct subclasses of a class."""
    bases = sorted({e.to_id for e in graph.edges if e.from_id == class_id and e.type == "inherits"})
    subclasses = sorted(
        {e.from_id for e in graph.edges if e.to_id == class_id and e.type == "inherits"}
    )
    return {"bases": bases, "subclasses": subclasses}


def get_file_dependents(graph: CodeGraph, file_path: str) -> list[str]:
    """Return the files that import the given file (file-level 'imports' edges)."""
    return sorted({e.from_id for e in graph.edges if e.to_id == file_path and e.type == "imports"})


def get_symbols_in_file(graph: CodeGraph, file_path: str) -> list[GraphNode]:
    """Return every function/class/method node defined in a given file."""
    return sorted(
        (n for n in graph.nodes.values() if n.file_path == file_path and n.type != "file"),
        key=lambda n: n.line_number,
    )


def get_impact_radius(graph: CodeGraph, symbol_id: str, max_depth: int = 3) -> dict[str, int]:
    """
    Traverse the graph backwards from a symbol (via 'calls' and 'inherits'
    edges) to find everything that would be affected if it changed, up to
    max_depth hops away.

    Returns {affected_symbol_id: distance_in_hops}, excluding the symbol itself.
    This is the graph-based analogue of tools.code_parser.get_affected_files,
    but at symbol granularity (function/class) rather than whole-file
    granularity, and following both call and inheritance relationships.
    """
    visited: dict[str, int] = {}
    frontier = [symbol_id]
    depth = 0

    while frontier and depth < max_depth:
        depth += 1
        next_frontier: list[str] = []
        for current_id in frontier:
            callers = [
                e.from_id
                for e in graph.edges
                if e.to_id == current_id and e.type in ("calls", "inherits")
            ]
            for caller_id in callers:
                if caller_id not in visited and caller_id != symbol_id:
                    visited[caller_id] = depth
                    next_frontier.append(caller_id)
        frontier = next_frontier

    return visited


def find_symbol_by_name(graph: CodeGraph, name: str) -> list[GraphNode]:
    """Find all nodes matching a short name (e.g. 'run_agent') across the repo.

    Useful when the caller has a name from an instruction or plan step but
    not the fully-qualified graph id.
    """
    return [n for n in graph.nodes.values() if n.name == name and n.type != "file"]


def summarize_code_graph(graph: CodeGraph, max_symbols_per_file: int = 15) -> str:
    """
    Return a compact, planner-prompt-friendly summary of the code graph.

    Lists each file's key symbols (functions/classes) and their most
    significant relationships (who they call, what they inherit from),
    so the planner can reason about structure without needing the raw
    graph — mirrors the style of tools.code_parser.summarize_project_map.
    """
    if not graph.nodes:
        return "(no code graph available)"

    lines = [f"Code graph: {len(graph.nodes)} symbols, {len(graph.edges)} relationships."]

    files = sorted({n.file_path for n in graph.nodes.values() if n.type == "file"})
    for file_path in files:
        symbols = get_symbols_in_file(graph, file_path)
        if not symbols:
            continue

        lines.append(f"\n{file_path}:")
        for symbol in symbols[:max_symbols_per_file]:
            detail_parts = [f"  - {symbol.type} {symbol.name} (line {symbol.line_number})"]

            if symbol.type == "class":
                hierarchy = get_class_hierarchy(graph, symbol.id)
                if hierarchy["bases"]:
                    base_names = [b.split("::")[-1] for b in hierarchy["bases"]]
                    detail_parts.append(f"inherits: {', '.join(base_names)}")

            callers = get_callers(graph, symbol.id)
            if callers:
                detail_parts.append(f"called by {len(callers)} symbol(s)")

            lines.append(" — ".join(detail_parts))

        if len(symbols) > max_symbols_per_file:
            lines.append(f"  ... and {len(symbols) - max_symbols_per_file} more symbol(s)")

    return "\n".join(lines)


def update_file_in_graph(
    graph: CodeGraph, file_path: str, new_content: str, all_files_by_path: dict[str, str]
) -> CodeGraph:
    """
    Incrementally update the graph after a single file's content changes,
    without rebuilding the entire repository graph from scratch.

    Removes every node/edge belonging to file_path, re-extracts its
    entities from new_content, and re-resolves relationships in both
    directions:
      - Edges FROM the changed file's symbols (its own calls/inherits) are
        recomputed fresh against the current graph's symbol names.
      - Edges FROM OTHER files TO symbols that used to live in file_path are
        re-resolved too, since a rename/removal in file_path can turn a
        previously-resolved edge stale (pointing at a symbol id that no
        longer exists) or newly-resolvable (a symbol that didn't exist
        before now does).

    Args:
        graph: The existing CodeGraph to update in place (and return).
        file_path: The file that changed.
        new_content: The file's new full source content.
        all_files_by_path: The complete current {file_path: content} map for
            the rest of the repo, needed to re-resolve cross-file edges
            correctly (e.g. new imports, or calls that now resolve
            differently).

    Returns:
        The same CodeGraph instance, updated in place.
    """
    # 1. Remove every node that belonged to this file (its own function/class/
    #    method/file nodes), and every edge touching those node ids.
    stale_node_ids = {
        node_id for node_id, node in graph.nodes.items() if node.file_path == file_path
    }
    for node_id in stale_node_ids:
        del graph.nodes[node_id]

    graph.edges = [
        e for e in graph.edges if e.from_id not in stale_node_ids and e.to_id not in stale_node_ids
    ]

    # 2. Re-extract the changed file's entities fresh from new_content.
    graph.add_node(
        GraphNode(id=file_path, type="file", name=file_path, file_path=file_path, line_number=1)
    )
    new_nodes, new_edges = extract_file_entities(new_content, file_path)
    for node in new_nodes:
        graph.add_node(node)
    graph.edges.extend(new_edges)

    # 3. Re-resolve "calls"/"inherits" edges, exactly as build_code_graph does,
    #    but only for edges whose target isn't already a real node id — this
    #    covers both the freshly re-extracted edges from this file AND any
    #    edges from other files that previously pointed at a raw name that
    #    might now resolve differently (e.g. a newly-added function in
    #    file_path that another file's call can now match).
    name_to_ids: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        if node.type in ("function", "class", "method"):
            name_to_ids.setdefault(node.name, []).append(node.id)

    resolved_edges: list[GraphEdge] = []
    for edge in graph.edges:
        if edge.type in ("calls", "inherits") and edge.to_id not in graph.nodes:
            short_name = edge.to_id.split(".")[-1]
            candidates = name_to_ids.get(short_name)
            if candidates:
                resolved_edges.append(
                    GraphEdge(from_id=edge.from_id, to_id=candidates[0], type=edge.type)
                )
            # unresolved (builtin/stdlib/third-party) -> dropped, same as build_code_graph
        else:
            resolved_edges.append(edge)
    graph.edges = resolved_edges

    # 4. Re-derive file-level "imports" edges for file_path specifically
    #    (both its own imports, and other files that import it — which
    #    can't change from this file's edit, but re-deriving is cheap and
    #    keeps this function self-contained rather than assuming).
    graph.edges = [
        e
        for e in graph.edges
        if not (e.type == "imports" and (e.from_id == file_path or e.to_id == file_path))
    ]

    from tools.code_parser import extract_python_imports

    updated_files = dict(all_files_by_path)
    updated_files[file_path] = new_content

    path_by_module: dict[str, str] = {}
    for path in updated_files:
        if path.endswith(".py"):
            normalized = path.replace("\\", "/")[: -len(".py")].replace("/", ".")
            path_by_module[normalized] = path

    # This file's own imports
    this_file_imports = extract_python_imports(new_content, file_path)
    for module in this_file_imports:
        target_file = path_by_module.get(module)
        if target_file:
            graph.add_edge(file_path, target_file, "imports")

    # Other files that import this file (their imports don't change, but
    # the edge was removed in the filter above, so restore it)
    for other_path, other_content in updated_files.items():
        if other_path == file_path or not other_path.endswith(".py"):
            continue
        other_imports = extract_python_imports(other_content, other_path)
        for module in other_imports:
            if path_by_module.get(module) == file_path:
                graph.add_edge(other_path, file_path, "imports")

    return graph

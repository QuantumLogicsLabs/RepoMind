from tools.code_graph import (
    build_code_graph,
    extract_file_entities,
    find_symbol_by_name,
    get_callees,
    get_callers,
    get_class_hierarchy,
    get_file_dependents,
    get_impact_radius,
    get_symbols_in_file,
    summarize_code_graph,
)


def test_extract_file_entities_finds_functions_and_classes():
    """AST extraction should find top-level functions and classes with correct line numbers."""
    content = (
        "def foo():\n"
        "    pass\n"
        "\n"
        "class Bar:\n"
        "    def method_one(self):\n"
        "        pass\n"
    )
    nodes, edges = extract_file_entities(content, "sample.py")

    node_ids = {n.id for n in nodes}
    assert "sample.py::foo" in node_ids
    assert "sample.py::Bar" in node_ids
    assert "sample.py::Bar.method_one" in node_ids

    foo_node = next(n for n in nodes if n.id == "sample.py::foo")
    assert foo_node.type == "function"
    assert foo_node.line_number == 1

    method_node = next(n for n in nodes if n.id == "sample.py::Bar.method_one")
    assert method_node.type == "method"


def test_extract_file_entities_handles_syntax_errors_gracefully():
    """A file with invalid syntax should return empty results, not raise."""
    nodes, edges = extract_file_entities("def broken(:\n    pass", "broken.py")
    assert nodes == []
    assert edges == []


def test_build_code_graph_resolves_calls_across_files():
    """A function in one file calling a function defined in another file
    should produce a correctly resolved 'calls' edge, not a dangling one.
    """
    files_by_path = {
        "utils.py": "def helper():\n    return 42\n",
        "main.py": "from utils import helper\n\ndef run():\n    return helper()\n",
    }
    graph = build_code_graph(files_by_path)

    helper_id = "utils.py::helper"
    run_id = "main.py::run"

    assert helper_id in graph.nodes
    assert run_id in graph.nodes

    calls_edge_exists = any(
        e.from_id == run_id and e.to_id == helper_id and e.type == "calls" for e in graph.edges
    )
    assert calls_edge_exists


def test_build_code_graph_captures_inheritance():
    """A class inheriting from another class in the same file should
    produce a resolved 'inherits' edge.
    """
    files_by_path = {
        "shapes.py": ("class Shape:\n    pass\n\nclass Circle(Shape):\n    pass\n"),
    }
    graph = build_code_graph(files_by_path)

    hierarchy = get_class_hierarchy(graph, "shapes.py::Circle")
    assert "shapes.py::Shape" in hierarchy["bases"]

    shape_hierarchy = get_class_hierarchy(graph, "shapes.py::Shape")
    assert "shapes.py::Circle" in shape_hierarchy["subclasses"]


def test_build_code_graph_tracks_file_level_imports():
    """File-level import relationships should appear as 'imports' edges,
    consistent with tools.code_parser's existing import graph.
    """
    files_by_path = {
        "a.py": "import b\n",
        "b.py": "x = 1\n",
    }
    graph = build_code_graph(files_by_path)

    dependents = get_file_dependents(graph, "b.py")
    assert "a.py" in dependents


def test_get_callers_and_callees_are_consistent():
    """get_callers(target) and get_callees(source) should agree on the same edge."""
    files_by_path = {
        "mod.py": "def a():\n    return b()\n\ndef b():\n    return 1\n",
    }
    graph = build_code_graph(files_by_path)

    callers_of_b = get_callers(graph, "mod.py::b")
    assert "mod.py::a" in callers_of_b

    callees_of_a = get_callees(graph, "mod.py::a")
    assert "mod.py::b" in callees_of_a


def test_get_impact_radius_follows_multi_hop_call_chain():
    """Impact radius should find symbols several calls away, with increasing depth."""
    files_by_path = {
        "chain.py": (
            "def level0():\n    return level1()\n\n"
            "def level1():\n    return level2()\n\n"
            "def level2():\n    return 1\n"
        ),
    }
    graph = build_code_graph(files_by_path)

    impact = get_impact_radius(graph, "chain.py::level2", max_depth=2)
    assert impact.get("chain.py::level1") == 1
    assert impact.get("chain.py::level0") == 2


def test_get_impact_radius_respects_max_depth():
    """Symbols beyond max_depth hops away should not appear in the result."""
    files_by_path = {
        "chain.py": (
            "def level0():\n    return level1()\n\n"
            "def level1():\n    return level2()\n\n"
            "def level2():\n    return 1\n"
        ),
    }
    graph = build_code_graph(files_by_path)

    impact = get_impact_radius(graph, "chain.py::level2", max_depth=1)
    assert "chain.py::level1" in impact
    assert "chain.py::level0" not in impact


def test_get_symbols_in_file_excludes_file_node_itself():
    """get_symbols_in_file should return functions/classes/methods only, not the file node."""
    files_by_path = {"mod.py": "def foo():\n    pass\n"}
    graph = build_code_graph(files_by_path)

    symbols = get_symbols_in_file(graph, "mod.py")
    symbol_ids = {s.id for s in symbols}
    assert "mod.py::foo" in symbol_ids
    assert "mod.py" not in symbol_ids


def test_find_symbol_by_name_matches_across_files():
    """find_symbol_by_name should find all nodes sharing a short name, regardless of file."""
    files_by_path = {
        "a.py": "def run():\n    pass\n",
        "b.py": "def run():\n    pass\n",
    }
    graph = build_code_graph(files_by_path)

    matches = find_symbol_by_name(graph, "run")
    match_ids = {m.id for m in matches}
    assert "a.py::run" in match_ids
    assert "b.py::run" in match_ids


def test_summarize_code_graph_produces_readable_text():
    """summarize_code_graph should return non-empty text mentioning known symbols."""
    files_by_path = {"mod.py": "def foo():\n    pass\n"}
    graph = build_code_graph(files_by_path)

    summary = summarize_code_graph(graph)
    assert "mod.py" in summary
    assert "foo" in summary


def test_summarize_code_graph_handles_empty_graph():
    """An empty graph should produce a clear placeholder message, not crash."""
    from tools.code_graph import CodeGraph

    summary = summarize_code_graph(CodeGraph())
    assert summary == "(no code graph available)"


def test_update_file_in_graph_reflects_rename_without_full_rebuild():
    """
    Incrementally updating one file's content should remove the old symbol,
    add the new one, leave other files' nodes untouched, and correctly drop
    (not leave dangling) edges from other files that referenced the old,
    now-removed symbol name.
    """
    from tools.code_graph import update_file_in_graph

    files_by_path = {
        "utils.py": "def old_name():\n    return 1\n",
        "main.py": "from utils import old_name\n\ndef run():\n    return old_name()\n",
    }
    graph = build_code_graph(files_by_path)

    # Sanity check on initial state before the update
    assert "utils.py::old_name" in graph.nodes
    assert "main.py::run" in get_callers(graph, "utils.py::old_name")

    new_content = "def new_name():\n    return 1\n"
    update_file_in_graph(graph, "utils.py", new_content, files_by_path)

    # Old symbol gone, new symbol present
    assert "utils.py::old_name" not in graph.nodes
    assert "utils.py::new_name" in graph.nodes

    # Other file's own nodes are untouched by the update
    assert "main.py::run" in graph.nodes

    # No dangling edge to the deleted symbol
    assert get_callers(graph, "utils.py::old_name") == []

    # main.py wasn't re-parsed, so it correctly does NOT call the new symbol either
    assert get_callers(graph, "utils.py::new_name") == []


def test_update_file_in_graph_resolves_new_cross_file_call():
    """
    After incrementally updating a file to add a function, another file's
    existing call to that (previously undefined) name should become
    resolved once the updated file is re-parsed into the graph.
    """
    from tools.code_graph import update_file_in_graph

    # main.py calls a function that doesn't exist yet in utils.py
    files_by_path = {
        "utils.py": "x = 1\n",
        "main.py": "from utils import new_helper\n\ndef run():\n    return new_helper()\n",
    }
    graph = build_code_graph(files_by_path)

    # Not yet resolvable — utils.py doesn't define new_helper yet
    assert "utils.py::new_helper" not in graph.nodes

    # Now utils.py is updated to actually define it
    updated_content = "def new_helper():\n    return 42\n"
    update_file_in_graph(graph, "utils.py", updated_content, files_by_path)

    assert "utils.py::new_helper" in graph.nodes

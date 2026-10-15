"""tests/test_semantic_code_search.py

Unit tests and benchmarks for Objective 20: Semantic Code Search.
"""

import pytest

from retrieval.chunker import CodeChunk, CodeChunker


class TestCodeChunker:
    """Task 1 tests: Code chunker parsing classes, functions, methods, and configs."""

    def test_chunk_python_file(self):
        chunker = CodeChunker()
        python_code = '''"""Module docstring."""

class Calculator:
    """Calculator class."""
    def add(self, a: int, b: int) -> int:
        """Add numbers."""
        return a + b

def standalone_func(x: int) -> int:
    """Standalone function."""
    return x * 2
'''
        chunks = chunker.chunk_file("math_utils.py", python_code)
        assert len(chunks) >= 3

        unit_types = {c.unit_type for c in chunks}
        assert "module" in unit_types
        assert "class" in unit_types
        assert "method" in unit_types
        assert "function" in unit_types

        class_chunk = next(c for c in chunks if c.unit_name == "Calculator")
        assert class_chunk.docstring == "Calculator class."

        method_chunk = next(c for c in chunks if c.unit_name == "Calculator.add")
        assert method_chunk.parent_symbol == "Calculator"
        assert method_chunk.docstring == "Add numbers."

        func_chunk = next(c for c in chunks if c.unit_name == "standalone_func")
        assert func_chunk.docstring == "Standalone function."

    def test_chunk_json_config(self):
        chunker = CodeChunker()
        json_code = (
            '{\n  "app": {\n    "name": "RepoMind"\n  },\n  "database": {\n    "port": 5432\n  }\n}'
        )
        chunks = chunker.chunk_file("config.json", json_code)
        assert len(chunks) == 2
        unit_names = {c.unit_name for c in chunks}
        assert "app" in unit_names
        assert "database" in unit_names

    def test_chunk_to_and_from_dict(self):
        chunk = CodeChunk(
            chunk_id="test.py::func::1",
            file_path="test.py",
            unit_type="function",
            unit_name="func",
            start_line=1,
            end_line=5,
            content="def func(): pass",
            docstring="Docstring",
            language="python",
        )
        d = chunk.to_dict()
        reconstructed = CodeChunk.from_dict(d)
        assert reconstructed.chunk_id == chunk.chunk_id
        assert reconstructed.unit_name == chunk.unit_name
        assert reconstructed.docstring == chunk.docstring


class TestCodeEmbeddingsAndStore:
    """Task 2 tests: Embedding generation and vector store persistence & search."""

    def test_split_identifier_and_embeddings(self):
        from retrieval.embeddings import CodeEmbeddingProvider, split_identifier

        assert split_identifier("SemanticRetriever") == ["semantic", "retriever"]
        assert split_identifier("calculate_total_price") == ["calculate", "total", "price"]

        provider = CodeEmbeddingProvider(vector_dim=128)
        chunk = CodeChunk(
            chunk_id="math.py::add::1",
            file_path="math.py",
            unit_type="function",
            unit_name="add_numbers",
            start_line=1,
            end_line=3,
            content="def add_numbers(a, b): return a + b",
            docstring="Add two numbers together.",
            language="python",
        )
        vec = provider.embed_chunk(chunk)
        assert len(vec) == 128
        assert sum(v * v for v in vec) > 0.9  # Normalized vector

    def test_code_vector_store_persistence_and_search(self, tmp_path):
        from retrieval.store import CodeVectorStore

        store = CodeVectorStore(storage_dir=tmp_path)
        chunker = CodeChunker()

        py_code = """
def calculate_area(radius: float) -> float:
    \"\"\"Compute circle area.\"\"\"
    return 3.14159 * radius * radius

def format_user_name(first: str, last: str) -> str:
    \"\"\"Format name string.\"\"\"
    return f"{first} {last}"
"""
        chunks = chunker.chunk_file("geometry.py", py_code)
        repo_id = "test_org/test_repo"

        added = store.index_chunks(repo_id, chunks)
        assert added >= 2

        # Search query matching circle area
        results = store.search_vector(repo_id, query="circle area math radius", top_k=2)
        assert len(results) >= 1
        top_chunk, score = results[0]
        assert top_chunk.unit_name == "calculate_area"
        assert score > 0.0


class TestHybridCodeRetriever:
    """Task 3 tests: Hybrid semantic + lexical + structural code search."""

    def test_hybrid_search_combines_scores(self, tmp_path):
        from retrieval.search import HybridCodeRetriever, SearchQuery
        from retrieval.store import CodeVectorStore

        store = CodeVectorStore(storage_dir=tmp_path)
        chunker = CodeChunker()

        file_content_1 = """
class UserAuthenticationService:
    \"\"\"Handles OAuth and JWT login validation.\"\"\"
    def login_user(self, email: str, password_hash: str) -> str:
        \"\"\"Verify user credentials and yield JWT token.\"\"\"
        return "jwt_token_xyz"
"""
        file_content_2 = """
class PaymentGateway:
    \"\"\"Processes Stripe and PayPal transactions.\"\"\"
    def process_charge(self, amount_cents: int) -> bool:
        return True
"""
        chunks_1 = chunker.chunk_file("auth/service.py", file_content_1)
        chunks_2 = chunker.chunk_file("billing/payment.py", file_content_2)

        repo_id = "org/hybrid-test"
        store.index_chunks(repo_id, chunks_1 + chunks_2)

        retriever = HybridCodeRetriever(store)
        query = SearchQuery(
            query="JWT login OAuth user authentication",
            target_files=["auth/service.py"],
            target_symbols=["UserAuthenticationService"],
            top_k=2,
        )

        results = retriever.search(repo_id, query)
        assert len(results) >= 1
        top_chunk, score = results[0]
        assert top_chunk.unit_name in {
            "UserAuthenticationService",
            "UserAuthenticationService.login_user",
        }
        assert score > 0.3


class TestCodeReranker:
    """Task 4 tests: Intent detection, symbol exact match boost, and deduplication."""

    def test_intent_detection(self):
        from retrieval.reranker import CodeReranker

        reranker = CodeReranker()
        assert reranker.detect_intent("Write unit test for user login") == "test"
        assert reranker.detect_intent("Where are settings configured in toml?") == "config"
        assert reranker.detect_intent("Implement parser class method") == "implementation"

    def test_deduplication_and_exact_symbol_boost(self):
        from retrieval.reranker import CodeReranker

        reranker = CodeReranker()

        chunk_class = CodeChunk(
            chunk_id="auth.py::AuthService::1",
            file_path="auth.py",
            unit_type="class",
            unit_name="AuthService",
            start_line=1,
            end_line=50,
            content="class AuthService:\n    def login(self): pass",
        )
        chunk_method = CodeChunk(
            chunk_id="auth.py::AuthService.login::10",
            file_path="auth.py",
            unit_type="method",
            unit_name="AuthService.login",
            start_line=10,
            end_line=20,
            content="def login(self): pass",
            parent_symbol="AuthService",
        )

        candidates = [
            (chunk_class, 0.8),
            (chunk_method, 0.82),
        ]

        reranked = reranker.rerank("login method in AuthService", candidates, top_k=5)
        # Because lines 10-20 overlap > 75% with lines 1-50 in auth.py, lower ranking block is suppressed
        assert len(reranked) == 1
        assert reranked[0][0].chunk_id == chunk_method.chunk_id


class TestSemanticContextBuilder:
    """Task 5 tests: Prompt formatting and token budgeting."""

    def test_context_builder_token_budgeting(self):
        from retrieval.context_builder import SemanticContextBuilder

        builder = SemanticContextBuilder(max_tokens=200)

        c1 = CodeChunk(
            chunk_id="f1.py::func1::1",
            file_path="f1.py",
            unit_type="function",
            unit_name="func1",
            start_line=1,
            end_line=5,
            content="def func1(): return 42",
            language="python",
        )
        c2 = CodeChunk(
            chunk_id="f2.py::func2::1",
            file_path="f2.py",
            unit_type="function",
            unit_name="func2",
            start_line=1,
            end_line=50,
            content="def func2():\n" + "    print('hello world')\n" * 100,
            language="python",
        )

        ranked = [(c1, 0.9), (c2, 0.8)]
        ctx = builder.build_context(ranked, max_tokens=150)

        assert len(ctx.selected_chunks) >= 1
        assert "f1.py" in ctx.included_files
        assert ctx.total_tokens <= 200
        assert "## Semantic Code Retrieval Context" in ctx.formatted_text


class TestPlannerExecutorRetrievalIntegration:
    """Task 6 tests: TaskPlanner and AgentChain retrieval context integration."""

    def test_planner_accepts_retrieved_code_context(self):
        from unittest.mock import MagicMock

        from agent.planner import Plan, PlanStep, TaskPlanner

        mock_llm = MagicMock()
        mock_plan = Plan(
            steps=[
                PlanStep(
                    id=1,
                    task="Add method",
                    target_files=["auth.py"],
                    target_function="AuthService.login",
                    new_logic="Return token",
                    expected_output="Token returned",
                    acceptance_criteria="Assert token is string",
                )
            ]
        )
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_plan

        planner = TaskPlanner(llm=mock_llm)
        planner.build_chain = MagicMock(return_value=mock_chain)

        code_context = "## Semantic Code Retrieval Context\n### File: auth.py (class: AuthService)\n```python\nclass AuthService: pass\n```"
        plan = planner.plan(
            instruction="Modify auth login method",
            context_messages=[],
            retrieved_code_context=code_context,
        )

        assert len(plan.steps) == 1
        mock_chain.invoke.assert_called_once()
        invoked_args = mock_chain.invoke.call_args[0][0]
        assert invoked_args["retrieved_code_context"] == code_context


class TestRetrievalBenchmarks:
    """Task 7 benchmarks: Testing hybrid code retrieval accuracy on representative repository queries."""

    @pytest.fixture
    def indexed_repo(self, tmp_path):
        from retrieval import CodeChunker, CodeVectorStore

        store = CodeVectorStore(storage_dir=tmp_path)
        chunker = CodeChunker()

        files = {
            "memory/store.py": "class PersistentVectorStore:\n    '''File-backed persistent vector store.'''\n    def add(self, memory): pass\n    def search(self, query): pass",
            "agent/planner.py": "class TaskPlanner:\n    '''Decomposes user instructions into plan steps.'''\n    def plan(self, instruction): pass",
            "retrieval/chunker.py": "class CodeChunker:\n    '''Parses source files into semantic units using Python AST.'''\n    def chunk_python(self, content): pass",
            "config/settings.py": "class Settings:\n    '''Loads application environment variables.'''\n    llm_model: str = 'gpt-4o'\n    env: str = 'development'",
        }

        repo_id = "repomind/benchmark"
        chunks = chunker.chunk_repository(files)
        store.index_chunks(repo_id, chunks)
        return store, repo_id

    def test_query_vector_store_persistence(self, indexed_repo):
        from retrieval import HybridCodeRetriever, SearchQuery

        store, repo_id = indexed_repo
        retriever = HybridCodeRetriever(store)

        results = retriever.search(
            repo_id, SearchQuery(query="Find persistent vector store memory search", top_k=3)
        )
        assert len(results) >= 1
        top_files = [c.file_path for c, _ in results]
        assert "memory/store.py" in top_files

    def test_query_planner_prompt_construction(self, indexed_repo):
        from retrieval import HybridCodeRetriever, SearchQuery

        store, repo_id = indexed_repo
        retriever = HybridCodeRetriever(store)

        results = retriever.search(
            repo_id, SearchQuery(query="Where is TaskPlanner instructions plan generated?", top_k=3)
        )
        assert len(results) >= 1
        top_files = [c.file_path for c, _ in results]
        assert "agent/planner.py" in top_files

    def test_query_code_chunker_ast(self, indexed_repo):
        from retrieval import HybridCodeRetriever, SearchQuery

        store, repo_id = indexed_repo
        retriever = HybridCodeRetriever(store)

        results = retriever.search(
            repo_id, SearchQuery(query="Locate code chunker Python AST parsing", top_k=3)
        )
        assert len(results) >= 1
        top_files = [c.file_path for c, _ in results]
        assert "retrieval/chunker.py" in top_files

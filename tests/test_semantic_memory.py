"""tests/test_semantic_memory.py

Comprehensive tests for RepoMind persistent semantic memory system.
"""

import pytest

from memory.models import MemoryCategory, RepositoryMemory


class TestMemoryModels:
    """Task 1 tests: Repository-scoped memory model & explicit memory types."""

    def test_memory_creation_and_defaults(self):
        mem = RepositoryMemory(
            repo_id="owner/repo-a",
            category=MemoryCategory.ARCHITECTURE,
            content="RepoMind uses FastApi and LangChain chain executor pattern.",
            file_paths=["api/main.py", "agent/chain.py"],
            symbols=["AgentChain"],
        )

        assert mem.repo_id == "owner/repo-a"
        assert mem.category == MemoryCategory.ARCHITECTURE
        assert mem.is_stale is False
        assert mem.version == 1
        assert "api/main.py" in mem.file_paths
        assert "AgentChain" in mem.symbols
        assert mem.summary.startswith("RepoMind uses FastApi")

    def test_serialization_deserialization(self):
        mem = RepositoryMemory(
            repo_id="owner/repo-b",
            category="decision",
            content="Use Groq rotation for zero 429 errors.",
            summary="Groq key rotation rule",
            metadata={"author": "team"},
        )
        data = mem.to_dict()
        restored = RepositoryMemory.from_dict(data)

        assert restored.id == mem.id
        assert restored.repo_id == "owner/repo-b"
        assert restored.category == MemoryCategory.DECISION
        assert restored.summary == "Groq key rotation rule"
        assert restored.metadata["author"] == "team"

    def test_context_string_formatting(self):
        mem = RepositoryMemory(
            repo_id="owner/repo-c",
            category=MemoryCategory.CONSTRAINT,
            content="Never modify global state in multithreaded handlers.",
            file_paths=["utils/job_manager.py"],
            symbols=["JobManager"],
        )
        context_str = mem.to_context_string()

        assert "[CONSTRAINT]" in context_str
        assert "Never modify global state" in context_str
        assert "[Files: utils/job_manager.py]" in context_str
        assert "[Symbols: JobManager]" in context_str


class TestVectorStore:
    """Task 2 tests: Embeddings and persistent vector store with repository isolation."""

    @pytest.fixture
    def store(self, tmp_path):
        from memory.store import PersistentVectorStore

        return PersistentVectorStore(storage_dir=tmp_path)

    def test_repo_isolation(self, store):
        mem1 = RepositoryMemory(
            repo_id="org/repo-1",
            category=MemoryCategory.ARCHITECTURE,
            content="Repo 1 uses FastAPI routes.",
        )
        mem2 = RepositoryMemory(
            repo_id="org/repo-2",
            category=MemoryCategory.ARCHITECTURE,
            content="Repo 2 uses Django framework.",
        )
        store.add(mem1)
        store.add(mem2)

        repo1_mems = store.get_all("org/repo-1")
        repo2_mems = store.get_all("org/repo-2")

        assert len(repo1_mems) == 1
        assert repo1_mems[0].content == "Repo 1 uses FastAPI routes."
        assert len(repo2_mems) == 1
        assert repo2_mems[0].content == "Repo 2 uses Django framework."

    def test_vector_search_and_similarity(self, store):
        mem1 = RepositoryMemory(
            repo_id="org/search-test",
            category=MemoryCategory.DECISION,
            content="Always use pytest-asyncio for testing asynchronous routes.",
            summary="pytest asyncio rule",
        )
        mem2 = RepositoryMemory(
            repo_id="org/search-test",
            category=MemoryCategory.CONVENTION,
            content="Format python code with black and ruff linter.",
            summary="code formatting rule",
        )
        store.add(mem1)
        store.add(mem2)

        results = store.search("org/search-test", query="async testing pytest", top_k=2)
        assert len(results) >= 1
        top_mem, score = results[0]
        assert top_mem.id == mem1.id
        assert score > 0.0

    def test_persistence_across_instances(self, tmp_path):
        from memory.store import PersistentVectorStore

        store1 = PersistentVectorStore(storage_dir=tmp_path)
        mem = RepositoryMemory(
            repo_id="org/persist-repo",
            category=MemoryCategory.CONSTRAINT,
            content="Keep dependencies lightweight.",
        )
        mem_id = store1.add(mem)

        # Re-instantiate store with same dir
        store2 = PersistentVectorStore(storage_dir=tmp_path)
        retrieved = store2.get("org/persist-repo", mem_id)
        assert retrieved is not None
        assert retrieved.content == "Keep dependencies lightweight."


class TestSemanticRetrieval:
    """Task 3 tests: Semantic retrieval selecting relevant context."""

    @pytest.fixture
    def store_and_retriever(self, tmp_path):
        from memory.retrieval import SemanticRetriever
        from memory.store import PersistentVectorStore

        store = PersistentVectorStore(storage_dir=tmp_path)
        retriever = SemanticRetriever(store)
        return store, retriever

    def test_composite_scoring_retrieval(self, store_and_retriever):
        from memory.retrieval import QueryContext

        store, retriever = store_and_retriever
        repo_id = "org/retrieval-test"

        mem_arch = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.ARCHITECTURE,
            content="API routing layer uses FastAPI routes and custom error handlers.",
            file_paths=["api/routes.py", "api/errors.py"],
            symbols=["router", "handle_error"],
        )
        mem_db = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.DECISION,
            content="Database connections must use connection pooling.",
            file_paths=["db/connection.py"],
            symbols=["get_pool"],
        )
        store.add(mem_arch)
        store.add(mem_db)

        context = QueryContext(
            instruction="Add error handling to FastAPI routes",
            file_paths=["api/routes.py"],
            symbols=["router"],
        )

        results = retriever.retrieve(repo_id, context)
        assert len(results) >= 1
        top_mem, score = results[0]
        assert top_mem.id == mem_arch.id
        assert score > 0.0

    def test_category_filtering(self, store_and_retriever):
        from memory.retrieval import QueryContext

        store, retriever = store_and_retriever
        repo_id = "org/cat-filter"

        mem_dec = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.DECISION,
            content="Use Groq API key rotator.",
        )
        mem_conv = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.CONVENTION,
            content="Use snake_case for python variables.",
        )
        store.add(mem_dec)
        store.add(mem_conv)

        context = QueryContext(
            instruction="styling rules",
            categories=[MemoryCategory.CONVENTION],
        )

        results = retriever.retrieve(repo_id, context)
        assert len(results) == 1
        assert results[0][0].category == MemoryCategory.CONVENTION


class TestLifecycle:
    """Task 4 tests: Memory lifecycle management, deduplication, and stale handling."""

    @pytest.fixture
    def store_and_lifecycle(self, tmp_path):
        from memory.lifecycle import MemoryLifecycleManager
        from memory.store import PersistentVectorStore

        store = PersistentVectorStore(storage_dir=tmp_path)
        lifecycle = MemoryLifecycleManager(store, deduplication_threshold=0.80)
        return store, lifecycle

    def test_deduplication_and_merging(self, store_and_lifecycle):
        store, lifecycle = store_and_lifecycle
        repo_id = "org/dedup-repo"

        mem1 = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.ARCHITECTURE,
            content="RepoMind pipeline executes plan then step executor.",
            file_paths=["agent/chain.py"],
            symbols=["AgentChain"],
        )
        saved_1, created_1 = lifecycle.add_or_update_memory(mem1)
        assert created_1 is True

        # Second memory with nearly identical content and same category
        mem2 = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.ARCHITECTURE,
            content="RepoMind pipeline executes plan then step executor.",
            file_paths=["agent/executor.py"],
            symbols=["StepExecutor"],
        )
        saved_2, created_2 = lifecycle.add_or_update_memory(mem2)

        assert created_2 is False
        assert saved_2.id == saved_1.id
        assert saved_2.version == 2
        assert "agent/chain.py" in saved_2.file_paths
        assert "agent/executor.py" in saved_2.file_paths
        assert "StepExecutor" in saved_2.symbols

    def test_stale_invalidation_by_files(self, store_and_lifecycle):
        store, lifecycle = store_and_lifecycle
        repo_id = "org/stale-repo"

        mem = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.DECISION,
            content="Old API schema configuration.",
            file_paths=["api/schemas.py"],
        )
        lifecycle.add_or_update_memory(mem)

        active_before = store.get_all(repo_id, include_stale=False)
        assert len(active_before) == 1

        count = lifecycle.invalidate_by_files(repo_id, ["api/schemas.py"])
        assert count == 1

        active_after = store.get_all(repo_id, include_stale=False)
        assert len(active_after) == 0

        stale_all = store.get_all(repo_id, include_stale=True)
        assert len(stale_all) == 1
        assert stale_all[0].is_stale is True


class TestPlannerIntegration:
    """Task 5 tests: Integrating retrieved memories into planning context with token budgeting."""

    @pytest.fixture
    def memory_manager(self, tmp_path):
        from memory.manager import SemanticMemoryManager

        return SemanticMemoryManager(storage_dir=tmp_path)

    def test_format_memories_prompt_and_token_budget(self, memory_manager):
        mem1 = RepositoryMemory(
            repo_id="org/prompt-test",
            category=MemoryCategory.ARCHITECTURE,
            content="Microservice architecture with gRPC.",
            file_paths=["proto/service.proto"],
        )
        mem2 = RepositoryMemory(
            repo_id="org/prompt-test",
            category=MemoryCategory.CONVENTION,
            content="Use Google style docstrings for Python code.",
            file_paths=["utils/logging.py"],
        )

        formatted = memory_manager.format_memories_for_prompt([mem1, mem2], max_tokens=1500)
        assert "REPOSITORY PERSISTENT SEMANTIC MEMORY" in formatted
        assert "[ARCHITECTURE]" in formatted
        assert "Microservice architecture" in formatted
        assert "[CONVENTION]" in formatted

    def test_token_trimming_exceeding_budget(self, memory_manager):
        large_mems = [
            RepositoryMemory(
                repo_id="org/trim-test",
                category=MemoryCategory.DECISION,
                content=f"Decision rule detail {i} " + ("word " * 100),
                summary=f"Decision summary {i}",
            )
            for i in range(10)
        ]

        # Small token budget should retain fewer memories
        formatted_small = memory_manager.format_memories_for_prompt(large_mems, max_tokens=100)
        assert "Decision summary 0" in formatted_small
        # Decision summary 9 should be trimmed out
        assert "Decision summary 9" not in formatted_small


class TestPostExecutionMemory:
    """Task 6 tests: Post-execution and PR memory updates."""

    @pytest.fixture
    def mock_llm_and_chain(self, tmp_path):
        from unittest.mock import MagicMock

        from agent.chain import AgentChain
        from memory.manager import SemanticMemoryManager

        mock_llm = MagicMock()
        sem_mem = SemanticMemoryManager(storage_dir=tmp_path)
        chain = AgentChain(llm=mock_llm, tools=[], semantic_memory=sem_mem)
        return chain, sem_mem

    def test_record_pr_memory(self, mock_llm_and_chain):
        chain, sem_mem = mock_llm_and_chain
        repo_id = "org/pr-repo"

        chain.record_pr_memory(
            repo_id=repo_id,
            pr_title="Add semantic memory engine",
            pr_url="https://github.com/org/pr-repo/pull/42",
            file_paths=["memory/manager.py", "agent/chain.py"],
        )

        stored = sem_mem.store.get_all(repo_id)
        assert len(stored) == 1
        assert stored[0].category == MemoryCategory.DECISION
        assert "pull/42" in stored[0].content
        assert "memory/manager.py" in stored[0].file_paths

    def test_post_execution_auto_memory_and_stale_invalidation(self, mock_llm_and_chain, tmp_path):
        from unittest.mock import MagicMock

        from agent.executor import ExecutorOutput, FileChange, StepExecutionResult
        from agent.planner import Plan, PlanStep

        chain, sem_mem = mock_llm_and_chain
        repo_id = "org/auto-exec"

        # Pre-existing memory for file to be modified
        old_mem = RepositoryMemory(
            repo_id=repo_id,
            category=MemoryCategory.ARCHITECTURE,
            content="Original architecture in api/main.py",
            file_paths=["api/main.py"],
        )
        sem_mem.lifecycle.add_or_update_memory(old_mem)

        # Mock planner and executor
        mock_plan = Plan(
            steps=[
                PlanStep(
                    id=1,
                    task="Update main route",
                    target_files=["api/main.py"],
                    target_function="app",
                    new_logic="Add metrics route",
                    expected_output="Route added",
                    acceptance_criteria="200 OK",
                )
            ]
        )
        chain.planner.plan = MagicMock(return_value=mock_plan)

        file_change = FileChange(
            filename="api/main.py", updated_content="app = FastAPI()", reason="Added route"
        )
        mock_execution = ExecutorOutput(
            results=[
                StepExecutionResult(
                    step_id=1,
                    step_task="Update main route",
                    tool_name="code_parser",
                    file_changes=[file_change],
                )
            ],
            all_file_changes=[file_change],
        )
        chain.executor.execute = MagicMock(return_value=mock_execution)

        chain.run_with_project_map(
            session_id="session-123",
            instruction="Add metrics route to api/main.py",
            repo_id=repo_id,
        )

        # Old memory for api/main.py should now be marked stale
        stale_mems = sem_mem.store.get_all(repo_id, include_stale=True)
        old_record = [m for m in stale_mems if m.id == old_mem.id][0]
        assert old_record.is_stale is True

        # New change history memory should exist
        active_mems = sem_mem.store.get_all(repo_id, include_stale=False)
        assert len(active_mems) == 1
        assert active_mems[0].category == MemoryCategory.CHANGE_HISTORY
        assert "api/main.py" in active_mems[0].file_paths

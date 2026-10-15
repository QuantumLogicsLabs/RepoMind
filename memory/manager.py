"""memory/manager.py

Unified Semantic Memory Manager facade for RepoMind.

Coordinates vector storage, retrieval, lifecycle, deduplication, and
context prompt injection with token limit budgeting.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from memory.lifecycle import MemoryLifecycleManager
from memory.models import MemoryCategory, RepositoryMemory
from memory.retrieval import QueryContext, SemanticRetriever
from memory.store import EmbeddingProvider, PersistentVectorStore

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Fast token count heuristic (~4 characters per token)."""
    return len(text) // 4


class SemanticMemoryManager:
    """Facade for managing persistent repository semantic memories."""

    def __init__(
        self,
        storage_dir: str | Path = ".repomind_memory",
        embedding_provider: EmbeddingProvider | None = None,
        deduplication_threshold: float = 0.85,
    ) -> None:
        self.store = PersistentVectorStore(
            storage_dir=storage_dir,
            embedding_provider=embedding_provider,
        )
        self.retriever = SemanticRetriever(self.store)
        self.lifecycle = MemoryLifecycleManager(
            store=self.store,
            deduplication_threshold=deduplication_threshold,
        )

    def add_memory(
        self,
        repo_id: str,
        category: MemoryCategory | str,
        content: str,
        summary: str = "",
        file_paths: list[str] | None = None,
        symbols: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[RepositoryMemory, bool]:
        """Add a memory entry or merge with similar existing memory."""
        memory = RepositoryMemory(
            repo_id=repo_id,
            category=category,
            content=content,
            summary=summary,
            file_paths=file_paths or [],
            symbols=symbols or [],
            metadata=metadata or {},
        )
        return self.lifecycle.add_or_update_memory(memory)

    def retrieve_relevant(
        self,
        repo_id: str,
        instruction: str,
        file_paths: list[str] | None = None,
        symbols: list[str] | None = None,
        categories: list[MemoryCategory | str] | None = None,
        top_k: int = 5,
        min_score: float = 0.05,
    ) -> list[RepositoryMemory]:
        """Retrieve relevant active memories for a given query context."""
        context = QueryContext(
            instruction=instruction,
            file_paths=file_paths or [],
            symbols=symbols or [],
            categories=categories,
            top_k=top_k,
            min_score=min_score,
        )
        scored = self.retriever.retrieve(repo_id=repo_id, context=context)
        memories = [m for m, score in scored]
        # Touch memories to track access frequency
        self.lifecycle.touch_memories(repo_id, [m.id for m in memories])
        return memories

    def format_memories_for_prompt(
        self,
        memories: list[RepositoryMemory],
        max_tokens: int = 1500,
    ) -> str:
        """
        Format memories into a clean prompt string for LLM planning,
        strictly respecting max_tokens context limits.
        """
        if not memories:
            return ""

        header = "=== REPOSITORY PERSISTENT SEMANTIC MEMORY ==="
        footer = "============================================"
        lines = [header]
        current_tokens = estimate_tokens(header) + estimate_tokens(footer)

        retained_count = 0
        for mem in memories:
            entry_str = mem.to_context_string()
            entry_tokens = estimate_tokens(entry_str)

            if current_tokens + entry_tokens <= max_tokens or retained_count == 0:
                lines.append(entry_str)
                current_tokens += entry_tokens
                retained_count += 1
            else:
                logger.info(
                    f"Trimmed semantic memory prompt context at {current_tokens}/{max_tokens} tokens."
                )
                break

        lines.append(footer)
        return "\n\n".join(lines)

    def invalidate_file_memories(self, repo_id: str, file_paths: list[str]) -> int:
        """Mark memories associated with specified file_paths as stale."""
        return self.lifecycle.invalidate_by_files(repo_id=repo_id, file_paths=file_paths)

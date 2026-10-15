"""memory/lifecycle.py

Memory Lifecycle Management for RepoMind:
- Creation and Smart Deduplication
- Automatic Updating & Merging
- Stale-Memory Invalidation (on file modifications or explicit updates)
- Access & Relevance Scoring Updates
"""

from __future__ import annotations

import logging

from memory.models import RepositoryMemory
from memory.store import PersistentVectorStore, cosine_similarity

logger = logging.getLogger(__name__)


class MemoryLifecycleManager:
    """Handles memory creation, deduplication, updating, and invalidation."""

    def __init__(
        self,
        store: PersistentVectorStore,
        deduplication_threshold: float = 0.85,
    ) -> None:
        self.store = store
        self.deduplication_threshold = deduplication_threshold

    def add_or_update_memory(self, memory: RepositoryMemory) -> tuple[RepositoryMemory, bool]:
        """
        Store a memory or merge it with a highly similar existing memory.

        Returns:
            (memory, created) where created is True if inserted as new, False if merged/updated.
        """
        repo_id = memory.repo_id
        # Ensure embedding exists for comparison
        if memory.embedding is None:
            full_text = f"{memory.category} {memory.summary} {memory.content} {' '.join(memory.file_paths)} {' '.join(memory.symbols)}"
            memory.embedding = self.store.embedding_provider.embed_text(full_text)

        existing_memories = self.store.get_all(repo_id, include_stale=False)

        best_match: RepositoryMemory | None = None
        highest_sim = 0.0

        for existing in existing_memories:
            # Only deduplicate within the same category
            if existing.category == memory.category and existing.embedding is not None:
                sim = cosine_similarity(memory.embedding, existing.embedding)
                if sim > highest_sim:
                    highest_sim = sim
                    best_match = existing

        if best_match is not None and highest_sim >= self.deduplication_threshold:
            logger.info(
                f"Deduplicating memory for {repo_id}: merging into existing {best_match.id} (similarity: {highest_sim:.2f})"
            )
            # Merge file paths & symbols
            merged_files = sorted(list(set(best_match.file_paths + memory.file_paths)))
            merged_symbols = sorted(list(set(best_match.symbols + memory.symbols)))

            best_match.content = memory.content
            best_match.summary = memory.summary
            best_match.file_paths = merged_files
            best_match.symbols = merged_symbols
            best_match.metadata.update(memory.metadata)

            self.store.update(best_match)
            return best_match, False
        else:
            self.store.add(memory)
            return memory, True

    def invalidate_by_files(self, repo_id: str, file_paths: list[str]) -> int:
        """
        Mark memories associated with the specified modified file_paths as stale.

        Returns:
            Count of invalidated memories.
        """
        if not file_paths:
            return 0

        target_set = {f.lower() for f in file_paths}
        memories = self.store.get_all(repo_id, include_stale=False)
        invalidated_count = 0

        for mem in memories:
            mem_files = {f.lower() for f in mem.file_paths}
            if target_set.intersection(mem_files):
                mem.is_stale = True
                self.store.update(mem)
                invalidated_count += 1
                logger.info(
                    f"Invalidated stale memory {mem.id} for repo {repo_id} due to file changes in {mem.file_paths}"
                )

        return invalidated_count

    def invalidate_memory(self, repo_id: str, memory_id: str) -> bool:
        """Mark a specific memory as stale."""
        mem = self.store.get(repo_id, memory_id)
        if mem and not mem.is_stale:
            mem.is_stale = True
            self.store.update(mem)
            return True
        return False

    def touch_memories(self, repo_id: str, memory_ids: list[str]) -> None:
        """Update access count and timestamp for specified memories."""
        for mem_id in memory_ids:
            mem = self.store.get(repo_id, mem_id)
            if mem and not mem.is_stale:
                mem.touch()
                self.store.update(mem)

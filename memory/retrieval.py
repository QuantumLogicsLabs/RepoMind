"""memory/retrieval.py

Semantic Retrieval Engine for selecting relevant repository memories based on
instruction, file paths, code symbols, and planned changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from memory.models import MemoryCategory, RepositoryMemory
from memory.store import PersistentVectorStore, cosine_similarity


@dataclass
class QueryContext:
    """Context parameters for querying repository memory."""

    instruction: str
    file_paths: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    categories: list[MemoryCategory | str] | None = None
    top_k: int = 5
    min_score: float = 0.05


class SemanticRetriever:
    """Ranks and retrieves memories relevant to current agent instruction and context."""

    def __init__(self, store: PersistentVectorStore) -> None:
        self.store = store

    def retrieve(
        self,
        repo_id: str,
        context: QueryContext,
        include_stale: bool = False,
    ) -> list[tuple[RepositoryMemory, float]]:
        """
        Retrieve and rank memories using composite scoring:
        Score = 0.50 * VectorSim + 0.25 * FileOverlap + 0.15 * SymbolOverlap + 0.10 * Recency/Access
        """
        memories = self.store.get_all(repo_id, include_stale=include_stale)
        if not memories:
            return []

        # Filter by category if requested
        if context.categories:
            valid_cats = {
                c.value if isinstance(c, MemoryCategory) else str(c).lower()
                for c in context.categories
            }
            memories = [
                m
                for m in memories
                if (
                    m.category.value
                    if isinstance(m.category, MemoryCategory)
                    else str(m.category).lower()
                )
                in valid_cats
            ]

        if not memories:
            return []

        # Build full query string & embedding
        query_parts = [context.instruction]
        if context.file_paths:
            query_parts.append(" ".join(context.file_paths))
        if context.symbols:
            query_parts.append(" ".join(context.symbols))
        full_query = " ".join(query_parts)

        query_vec = self.store.embedding_provider.embed_text(full_query)
        target_files = {f.lower() for f in context.file_paths}
        target_symbols = {s.lower() for s in context.symbols}

        now = time.time()
        scored: list[tuple[RepositoryMemory, float]] = []

        for mem in memories:
            # 1. Vector similarity
            vec_score = 0.0
            if mem.embedding is not None:
                vec_score = max(0.0, cosine_similarity(query_vec, mem.embedding))

            # 2. File overlap score
            file_score = 0.0
            if target_files and mem.file_paths:
                mem_files = {f.lower() for f in mem.file_paths}
                overlap = len(target_files.intersection(mem_files))
                file_score = overlap / max(len(target_files), len(mem_files))

            # 3. Symbol overlap score
            symbol_score = 0.0
            if target_symbols and mem.symbols:
                mem_syms = {s.lower() for s in mem.symbols}
                overlap = len(target_symbols.intersection(mem_syms))
                symbol_score = overlap / max(len(target_symbols), len(mem_syms))

            # 4. Recency & Access score (0.0 to 1.0)
            age_days = (now - mem.updated_at) / (24 * 3600)
            recency_score = 1.0 / (1.0 + 0.1 * age_days)
            access_boost = min(1.0, mem.access_count * 0.1)
            meta_score = 0.7 * recency_score + 0.3 * access_boost

            # Composite final score calculation
            final_score = (
                0.50 * vec_score + 0.25 * file_score + 0.15 * symbol_score + 0.10 * meta_score
            )

            if final_score >= context.min_score:
                scored.append((mem, round(final_score, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: context.top_k]

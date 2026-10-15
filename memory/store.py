"""memory/store.py

Persistent Vector Storage Engine and Embedding Generation for RepoMind.

Features:
- Built-in lightweight semantic embedding generator (n-gram hashing vectorizer)
- Support for external embedding providers via interface
- Cosine similarity vector search
- Per-repository persistent storage with filesystem JSON indexes
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from memory.models import RepositoryMemory


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingProvider:
    """Generate dense vector embeddings for text using a deterministic hashing vectorizer."""

    def __init__(self, vector_dim: int = 128) -> None:
        self.vector_dim = vector_dim

    def embed_text(self, text: str) -> list[float]:
        """Convert arbitrary text into a normalized embedding vector."""
        if not text:
            return [0.0] * self.vector_dim

        vec = [0.0] * self.vector_dim
        # Tokenize into word & n-gram tokens
        tokens = re.findall(r"\w+", text.lower())
        if not tokens:
            return vec

        # Add 1-grams and 2-grams
        all_features = list(tokens)
        for i in range(len(tokens) - 1):
            all_features.append(f"{tokens[i]}_{tokens[i+1]}")

        for feature in all_features:
            idx = abs(hash(feature)) % self.vector_dim
            vec[idx] += 1.0

        # L2 Normalize
        magnitude = math.sqrt(sum(val * val for val in vec))
        if magnitude > 0:
            vec = [val / magnitude for val in vec]

        return vec


class PersistentVectorStore:
    """File-backed, repository-isolated vector store for persistent semantic memories."""

    def __init__(
        self,
        storage_dir: str | Path = ".repomind_memory",
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.embedding_provider = embedding_provider or EmbeddingProvider()
        # Internal cache: repo_id -> {memory_id: RepositoryMemory}
        self._memories: dict[str, dict[str, RepositoryMemory]] = {}
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_repo_id(self, repo_id: str) -> str:
        """Convert repo_id to safe directory/file name."""
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", repo_id)

    def _get_repo_file_path(self, repo_id: str) -> Path:
        safe_id = self._sanitize_repo_id(repo_id)
        return self.storage_dir / f"repo_{safe_id}.json"

    def _load_repo(self, repo_id: str) -> dict[str, RepositoryMemory]:
        if repo_id in self._memories:
            return self._memories[repo_id]

        file_path = self._get_repo_file_path(repo_id)
        memories: dict[str, RepositoryMemory] = {}
        if file_path.exists():
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("memories", []):
                        mem = RepositoryMemory.from_dict(item)
                        memories[mem.id] = mem
            except Exception:
                memories = {}

        self._memories[repo_id] = memories
        return memories

    def _save_repo(self, repo_id: str) -> None:
        file_path = self._get_repo_file_path(repo_id)
        memories = self._load_repo(repo_id)
        data = {
            "repo_id": repo_id,
            "memories": [mem.to_dict() for mem in memories.values()],
        }
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_path.replace(file_path)

    def add(self, memory: RepositoryMemory) -> str:
        """Store a new memory. Generates embedding if missing."""
        if memory.embedding is None:
            full_text = f"{memory.category} {memory.summary} {memory.content} {' '.join(memory.file_paths)} {' '.join(memory.symbols)}"
            memory.embedding = self.embedding_provider.embed_text(full_text)

        memories = self._load_repo(memory.repo_id)
        memories[memory.id] = memory
        self._save_repo(memory.repo_id)
        return memory.id

    def get(self, repo_id: str, memory_id: str) -> RepositoryMemory | None:
        """Retrieve memory by ID for a specific repository."""
        memories = self._load_repo(repo_id)
        return memories.get(memory_id)

    def get_all(self, repo_id: str, include_stale: bool = False) -> list[RepositoryMemory]:
        """Get all memories for a repository."""
        memories = self._load_repo(repo_id)
        items = list(memories.values())
        if not include_stale:
            items = [m for m in items if not m.is_stale]
        return items

    def update(self, memory: RepositoryMemory) -> bool:
        """Update an existing memory."""
        memories = self._load_repo(memory.repo_id)
        if memory.id not in memories:
            return False
        memory.mark_updated()
        # Regenerate embedding if content changed
        full_text = f"{memory.category} {memory.summary} {memory.content} {' '.join(memory.file_paths)} {' '.join(memory.symbols)}"
        memory.embedding = self.embedding_provider.embed_text(full_text)
        memories[memory.id] = memory
        self._save_repo(memory.repo_id)
        return True

    def delete(self, repo_id: str, memory_id: str) -> bool:
        """Delete a memory from storage."""
        memories = self._load_repo(repo_id)
        if memory_id in memories:
            del memories[memory_id]
            self._save_repo(repo_id)
            return True
        return False

    def search(
        self,
        repo_id: str,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        include_stale: bool = False,
    ) -> list[tuple[RepositoryMemory, float]]:
        """Search memories using embedding cosine similarity."""
        memories = self.get_all(repo_id, include_stale=include_stale)
        if not memories:
            return []

        query_vector = self.embedding_provider.embed_text(query)
        scored: list[tuple[RepositoryMemory, float]] = []

        for mem in memories:
            if mem.embedding is None:
                continue
            sim = cosine_similarity(query_vector, mem.embedding)
            if sim >= min_score:
                scored.append((mem, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

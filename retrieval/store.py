"""retrieval/store.py

Persistent Vector Store for Code Chunks in RepoMind.
Maintains repository-isolated code chunk indexes with fast vector search.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from retrieval.chunker import CodeChunk
from retrieval.embeddings import CodeEmbeddingProvider, cosine_similarity


class CodeVectorStore:
    """File-backed, repository-isolated vector store for code unit chunks."""

    def __init__(
        self,
        storage_dir: str | Path = ".repomind_memory",
        embedding_provider: CodeEmbeddingProvider | None = None,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.embedding_provider = embedding_provider or CodeEmbeddingProvider()
        # Internal cache: repo_id -> {chunk_id: (CodeChunk, vector)}
        self._chunks: dict[str, dict[str, tuple[CodeChunk, list[float]]]] = {}
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_repo_id(self, repo_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", repo_id)

    def _get_repo_file_path(self, repo_id: str) -> Path:
        safe_id = self._sanitize_repo_id(repo_id)
        return self.storage_dir / f"code_index_{safe_id}.json"

    def _load_repo(self, repo_id: str) -> dict[str, tuple[CodeChunk, list[float]]]:
        if repo_id in self._chunks:
            return self._chunks[repo_id]

        file_path = self._get_repo_file_path(repo_id)
        repo_data: dict[str, tuple[CodeChunk, list[float]]] = {}

        if file_path.exists():
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("chunks", []):
                        chunk = CodeChunk.from_dict(item["chunk"])
                        vec = item["vector"]
                        repo_data[chunk.chunk_id] = (chunk, vec)
            except Exception:
                repo_data = {}

        self._chunks[repo_id] = repo_data
        return repo_data

    def _save_repo(self, repo_id: str) -> None:
        file_path = self._get_repo_file_path(repo_id)
        repo_data = self._load_repo(repo_id)

        items: list[dict[str, Any]] = []
        for chunk, vec in repo_data.values():
            items.append({"chunk": chunk.to_dict(), "vector": vec})

        data = {"repo_id": repo_id, "chunks": items}
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_path.replace(file_path)

    def index_chunks(self, repo_id: str, chunks: list[CodeChunk]) -> int:
        """Add or update multiple code chunks in the vector store."""
        repo_data = self._load_repo(repo_id)
        for chunk in chunks:
            vec = self.embedding_provider.embed_chunk(chunk)
            repo_data[chunk.chunk_id] = (chunk, vec)

        self._save_repo(repo_id)
        return len(chunks)

    def get_all_chunks(self, repo_id: str) -> list[CodeChunk]:
        """Return all indexed CodeChunks for a repository."""
        repo_data = self._load_repo(repo_id)
        return [c for c, _ in repo_data.values()]

    def get_chunks_by_file(self, repo_id: str, file_path: str) -> list[CodeChunk]:
        """Retrieve all code chunks belonging to a specific file."""
        repo_data = self._load_repo(repo_id)
        norm_target = file_path.replace("\\", "/")
        return [c for c, _ in repo_data.values() if c.file_path.replace("\\", "/") == norm_target]

    def search_vector(
        self,
        repo_id: str,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[CodeChunk, float]]:
        """Search indexed code chunks using embedding cosine similarity."""
        repo_data = self._load_repo(repo_id)
        if not repo_data:
            return []

        query_vec = self.embedding_provider.embed_text(query)
        results: list[tuple[CodeChunk, float]] = []

        for chunk, vec in repo_data.values():
            sim = cosine_similarity(query_vec, vec)
            if sim >= min_score:
                results.append((chunk, round(sim, 4)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

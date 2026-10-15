"""retrieval/search.py

Hybrid Code Retrieval Engine for RepoMind.
Combines dense vector similarity, lexical BM25/token overlap, and structural relevance
(exact symbol matching, target file hints, entry point priority).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from retrieval.chunker import CodeChunk
from retrieval.embeddings import split_identifier
from retrieval.store import CodeVectorStore


@dataclass
class SearchQuery:
    """Parameters for hybrid repository code search."""

    query: str
    target_files: list[str] = field(default_factory=list)
    target_symbols: list[str] = field(default_factory=list)
    unit_types: list[str] = field(default_factory=list)
    top_k: int = 10
    min_score: float = 0.05
    semantic_weight: float = 0.45
    lexical_weight: float = 0.35
    structural_weight: float = 0.20


class BM25Scorer:
    """Lightweight BM25 lexical scorer for code tokens."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def compute_score(
        self, query_tokens: list[str], chunk_tokens: list[str], avg_len: float
    ) -> float:
        if not query_tokens or not chunk_tokens:
            return 0.0

        doc_len = len(chunk_tokens)
        token_counts: dict[str, int] = {}
        for t in chunk_tokens:
            token_counts[t] = token_counts.get(t, 0) + 1

        score = 0.0
        for q in query_tokens:
            tf = token_counts.get(q, 0)
            if tf > 0:
                idf = 1.0  # Normalized IDF proxy for chunk retrieval
                denom = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / (avg_len or 1.0)))
                score += idf * (tf * (self.k1 + 1.0)) / denom

        # Normalize score between 0.0 and 1.0
        return min(1.0, score / max(1.0, len(query_tokens) * 2.0))


class HybridCodeRetriever:
    """Hybrid semantic + lexical + structural code retrieval engine."""

    def __init__(self, store: CodeVectorStore) -> None:
        self.store = store
        self.bm25 = BM25Scorer()

    def search(
        self,
        repo_id: str,
        query: SearchQuery | str,
    ) -> list[tuple[CodeChunk, float]]:
        """Perform hybrid search over indexed repository code chunks."""
        if isinstance(query, str):
            sq = SearchQuery(query=query)
        else:
            sq = query

        chunks = self.store.get_all_chunks(repo_id)
        if not chunks:
            return []

        # Filter by unit_types if specified
        if sq.unit_types:
            valid_types = {t.lower() for t in sq.unit_types}
            chunks = [c for c in chunks if c.unit_type.lower() in valid_types]

        if not chunks:
            return []

        # 1. Semantic Similarity Scores
        vector_results = self.store.search_vector(
            repo_id=repo_id,
            query=sq.query,
            top_k=len(chunks),
            min_score=0.0,
        )
        sem_map: dict[str, float] = {chunk.chunk_id: score for chunk, score in vector_results}

        # 2. Lexical Scores
        query_tokens = split_identifier(sq.query)
        avg_chunk_len = sum(len(split_identifier(c.content)) for c in chunks) / max(1, len(chunks))

        target_file_set = {f.lower().replace("\\", "/") for f in sq.target_files}
        target_symbol_set = {s.lower() for s in sq.target_symbols}

        scored: list[tuple[CodeChunk, float]] = []

        for chunk in chunks:
            chunk_tokens = (
                split_identifier(chunk.unit_name)
                + split_identifier(chunk.file_path)
                + (split_identifier(chunk.docstring) if chunk.docstring else [])
                + split_identifier(chunk.content)
            )

            # Lexical BM25 Score
            lex_score = self.bm25.compute_score(query_tokens, chunk_tokens, avg_chunk_len)

            # Structural Relevance Score
            struct_score = 0.0
            chunk_path_lower = chunk.file_path.lower().replace("\\", "/")
            chunk_symbol_lower = chunk.unit_name.lower()

            # Target file overlap bonus
            if target_file_set:
                for target_f in target_file_set:
                    if target_f in chunk_path_lower or chunk_path_lower in target_f:
                        struct_score += 0.5
                        break

            # Target symbol match bonus
            if target_symbol_set:
                for target_s in target_symbol_set:
                    if target_s in chunk_symbol_lower:
                        struct_score += 0.5
                        break

            # Query exact symbol/path match bonus
            for q_tok in query_tokens:
                if len(q_tok) > 2 and q_tok in chunk_symbol_lower:
                    struct_score += 0.2
                if len(q_tok) > 3 and q_tok in chunk_path_lower:
                    struct_score += 0.1

            struct_score = min(1.0, struct_score)
            sem_score = sem_map.get(chunk.chunk_id, 0.0)

            # Weighted Hybrid Score
            hybrid_score = (
                sq.semantic_weight * sem_score
                + sq.lexical_weight * lex_score
                + sq.structural_weight * struct_score
            )

            if hybrid_score >= sq.min_score:
                scored.append((chunk, round(hybrid_score, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: sq.top_k]

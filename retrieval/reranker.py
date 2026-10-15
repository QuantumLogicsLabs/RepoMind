"""retrieval/reranker.py

Code Reranker and Deduplicator for RepoMind.
Applies intent-aware re-scoring, exact symbol matching boosts,
and suppresses overlapping/redundant code snippets.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrieval.chunker import CodeChunk


def _line_overlap_ratio(start1: int, end1: int, start2: int, end2: int) -> float:
    """Calculate line range overlap ratio relative to smaller range."""
    overlap_start = max(start1, start2)
    overlap_end = min(end1, end2)
    if overlap_start > overlap_end:
        return 0.0
    overlap_len = overlap_end - overlap_start + 1
    min_len = min(end1 - start1 + 1, end2 - start2 + 1)
    return overlap_len / max(1.0, float(min_len))


class CodeReranker:
    """Reranks hybrid search results and eliminates duplicate or redundant code blocks."""

    def __init__(self, overlap_threshold: float = 0.75) -> None:
        self.overlap_threshold = overlap_threshold

    def detect_intent(self, query: str) -> str:
        """Infer query intent: 'test', 'config', 'implementation', or 'general'."""
        q_lower = query.lower()
        if any(
            term in q_lower for term in ("test", "unit test", "fixture", "assert", "mock", "pytest")
        ):
            return "test"
        if any(
            term in q_lower
            for term in ("config", "setting", "environment", "toml", "json", "yaml", "env")
        ):
            return "config"
        if any(
            term in q_lower
            for term in ("class", "function", "implement", "method", "logic", "parser")
        ):
            return "implementation"
        return "general"

    def rerank(
        self,
        query: str,
        candidates: list[tuple[CodeChunk, float]],
        top_k: int = 10,
    ) -> list[tuple[CodeChunk, float]]:
        """Rerank candidates with intent matching and line overlap deduplication."""
        if not candidates:
            return []

        intent = self.detect_intent(query)
        q_tokens = set(re.findall(r"\w+", query.lower()))

        rescored: list[tuple[CodeChunk, float]] = []

        for chunk, orig_score in candidates:
            score = orig_score
            file_path_lower = chunk.file_path.lower()
            unit_name_lower = chunk.unit_name.lower()

            # 1. Intent Alignment Boost / Penalty
            is_test_file = "test" in file_path_lower or "spec" in file_path_lower
            if intent == "test":
                if is_test_file:
                    score *= 1.25
            elif intent == "config":
                if chunk.unit_type == "config":
                    score *= 1.25
            elif intent == "implementation":
                if not is_test_file and chunk.unit_type in {"class", "function", "method"}:
                    score *= 1.15

            # 2. Exact Symbol Match Boost
            unit_tokens = set(re.findall(r"\w+", unit_name_lower))
            if q_tokens.intersection(unit_tokens):
                score *= 1.3

            rescored.append((chunk, round(score, 4)))

        # Sort by updated score descending
        rescored.sort(key=lambda x: x[1], reverse=True)

        # 3. Deduplication of Overlapping Line Ranges in Same File
        filtered: list[tuple[CodeChunk, float]] = []
        for chunk, score in rescored:
            duplicate = False
            for existing_chunk, _ in filtered:
                if chunk.file_path == existing_chunk.file_path:
                    overlap = _line_overlap_ratio(
                        chunk.start_line,
                        chunk.end_line,
                        existing_chunk.start_line,
                        existing_chunk.end_line,
                    )
                    if overlap >= self.overlap_threshold:
                        duplicate = True
                        break

            if not duplicate:
                filtered.append((chunk, score))

        return filtered[:top_k]

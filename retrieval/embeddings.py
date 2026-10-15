"""retrieval/embeddings.py

Dense vector embedding generator for source code units.
Splits camelCase and snake_case identifiers, weights symbol names and docstrings,
and computes normalized n-gram feature hashing vectors.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrieval.chunker import CodeChunk


def split_identifier(name: str) -> list[str]:
    """Split snake_case, camelCase, and PascalCase identifiers into sub-tokens."""
    if not name:
        return []
    # Split snake_case and dot notation
    parts = re.split(r"[._\-]", name)
    tokens: list[str] = []
    for part in parts:
        # Split camelCase / PascalCase
        sub = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)|[0-9]+", part)
        if sub:
            tokens.extend(s.lower() for s in sub)
        elif part:
            tokens.append(part.lower())
    return tokens


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two normalized float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class CodeEmbeddingProvider:
    """Generates dense embedding vectors for code units and natural language queries."""

    def __init__(self, vector_dim: int = 256) -> None:
        self.vector_dim = vector_dim

    def embed_text(self, text: str) -> list[float]:
        """Convert arbitrary query or text into a normalized embedding vector."""
        if not text:
            return [0.0] * self.vector_dim

        vec = [0.0] * self.vector_dim
        words = re.findall(r"\w+", text)

        all_tokens: list[str] = []
        for word in words:
            sub_tokens = split_identifier(word)
            all_tokens.extend(sub_tokens)

        if not all_tokens:
            return vec

        # Add 1-grams and 2-grams
        features = list(all_tokens)
        for i in range(len(all_tokens) - 1):
            features.append(f"{all_tokens[i]}_{all_tokens[i+1]}")

        for feature in features:
            idx = abs(hash(feature)) % self.vector_dim
            vec[idx] += 1.0

        # L2 Normalize
        magnitude = math.sqrt(sum(v * v for v in vec))
        if magnitude > 0:
            vec = [v / magnitude for v in vec]

        return vec

    def embed_chunk(self, chunk: CodeChunk) -> list[float]:
        """Generate a weighted embedding vector for a CodeChunk."""
        vec = [0.0] * self.vector_dim

        # 1. Symbol Name Tokens (Weight 3.0)
        symbol_tokens = split_identifier(chunk.unit_name)
        if chunk.parent_symbol:
            symbol_tokens.extend(split_identifier(chunk.parent_symbol))

        for tok in symbol_tokens:
            idx = abs(hash(tok)) % self.vector_dim
            vec[idx] += 3.0

        # 2. Unit Type & Path Tokens (Weight 1.5)
        path_tokens = split_identifier(chunk.file_path)
        for tok in path_tokens + [chunk.unit_type, chunk.language]:
            idx = abs(hash(tok)) % self.vector_dim
            vec[idx] += 1.5

        # 3. Docstring Tokens (Weight 2.0)
        if chunk.docstring:
            doc_words = re.findall(r"\w+", chunk.docstring)
            for w in doc_words:
                for tok in split_identifier(w):
                    idx = abs(hash(tok)) % self.vector_dim
                    vec[idx] += 2.0

        # 4. Code Body Tokens (Weight 1.0)
        body_words = re.findall(r"\w+", chunk.content)
        for w in body_words:
            for tok in split_identifier(w):
                idx = abs(hash(tok)) % self.vector_dim
                vec[idx] += 1.0

        # L2 Normalize
        magnitude = math.sqrt(sum(v * v for v in vec))
        if magnitude > 0:
            vec = [v / magnitude for v in vec]

        return vec

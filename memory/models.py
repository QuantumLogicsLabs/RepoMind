"""memory/models.py

Repository-scoped memory model definitions for RepoMind.

Supports explicit memory categories:
- ARCHITECTURE: Repository architecture facts, structural layout, module dependencies.
- CONVENTION: Coding standards, formatting guidelines, project conventions.
- DECISION: Key architectural decisions (ADRs) and design rationale.
- CHANGE_HISTORY: Summaries of past executions, feature implementations, and PRs.
- CONSTRAINT: Learned constraints, safety rules, invariants, and known pitfalls.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any


class MemoryCategory(StrEnum):
    ARCHITECTURE = "architecture"
    CONVENTION = "convention"
    DECISION = "decision"
    CHANGE_HISTORY = "change_history"
    CONSTRAINT = "constraint"


@dataclass
class RepositoryMemory:
    """Represents a single durable semantic memory entry scoped to a repository."""

    repo_id: str
    category: MemoryCategory | str
    content: str
    summary: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    file_paths: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    is_stale: bool = False
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.category, str):
            try:
                self.category = MemoryCategory(self.category.lower())
            except ValueError:
                # Keep custom or raw string category fallback
                pass
        if not self.summary:
            # Use truncated content as default summary if not explicitly provided
            self.summary = self.content[:150] + ("..." if len(self.content) > 150 else "")

    def mark_updated(self) -> None:
        self.version += 1
        self.updated_at = time.time()

    def touch(self) -> None:
        self.access_count += 1
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize memory to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "category": (
                self.category.value if isinstance(self.category, Enum) else str(self.category)
            ),
            "content": self.content,
            "summary": self.summary,
            "file_paths": self.file_paths,
            "symbols": self.symbols,
            "metadata": self.metadata,
            "embedding": self.embedding,
            "is_stale": self.is_stale,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepositoryMemory:
        """Deserialize memory from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            repo_id=data["repo_id"],
            category=data["category"],
            content=data["content"],
            summary=data.get("summary", ""),
            file_paths=data.get("file_paths", []),
            symbols=data.get("symbols", []),
            metadata=data.get("metadata", {}),
            embedding=data.get("embedding"),
            is_stale=data.get("is_stale", False),
            version=data.get("version", 1),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            access_count=data.get("access_count", 0),
        )

    def to_context_string(self) -> str:
        """Format memory into a concise string representation for LLM prompts."""
        category_str = (
            self.category.value.upper()
            if isinstance(self.category, Enum)
            else str(self.category).upper()
        )
        files_str = f" [Files: {', '.join(self.file_paths)}]" if self.file_paths else ""
        symbols_str = f" [Symbols: {', '.join(self.symbols)}]" if self.symbols else ""
        return f"[{category_str}] {self.summary}{files_str}{symbols_str}\nDetails: {self.content}"

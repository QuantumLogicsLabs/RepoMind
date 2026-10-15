"""retrieval/context_builder.py

Semantic Context Builder for RepoMind LLM Prompts.
Assembles retrieved code chunks into clean, structured Markdown/XML context snippets
while enforcing strict token budget limits and preventing duplicate context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrieval.chunker import CodeChunk


def _estimate_tokens(text: str) -> int:
    """Fast token estimation (~4 chars per token)."""
    return len(text) // 4


@dataclass
class RetrievedContext:
    """Structured context output for prompt injection."""

    formatted_text: str
    selected_chunks: list[CodeChunk] = field(default_factory=list)
    total_tokens: int = 0
    included_files: list[str] = field(default_factory=list)
    included_symbols: list[str] = field(default_factory=list)


class SemanticContextBuilder:
    """Formats retrieved code chunks into token-budgeted prompt sections."""

    def __init__(self, max_tokens: int = 8000) -> None:
        self.max_tokens = max_tokens

    def build_context(
        self,
        chunks_with_scores: list[tuple[CodeChunk, float]],
        max_tokens: int | None = None,
        header_title: str = "Semantic Code Retrieval Context",
    ) -> RetrievedContext:
        """Format ranked code chunks into a token-budgeted markdown block."""
        budget = max_tokens or self.max_tokens

        if not chunks_with_scores:
            return RetrievedContext(formatted_text="", total_tokens=0)

        selected_chunks: list[CodeChunk] = []
        included_files: set[str] = set()
        included_symbols: set[str] = set()

        snippet_blocks: list[str] = []
        header = f"## {header_title}\n\nThe following code regions were retrieved from the repository based on semantic, lexical, and structural relevance:\n"
        current_tokens = _estimate_tokens(header)

        for chunk, score in chunks_with_scores:
            lang_label = chunk.language or "text"
            block_header = (
                f"\n### File: `{chunk.file_path}` ({chunk.unit_type}: `{chunk.unit_name}`, "
                f"Lines {chunk.start_line}-{chunk.end_line}, Relevance Score: {score:.2f})\n"
            )
            code_fence = f"```{lang_label}\n{chunk.content}\n```\n"
            full_block = block_header + code_fence
            block_tokens = _estimate_tokens(full_block)

            if current_tokens + block_tokens > budget:
                # If block is too large, check if we can truncate content
                remaining_budget = (
                    budget
                    - current_tokens
                    - _estimate_tokens(block_header + f"```{lang_label}\n... [Truncated]\n```\n")
                )
                if remaining_budget > 100:
                    max_chars = remaining_budget * 4
                    truncated_content = (
                        chunk.content[:max_chars] + "\n... [Truncated due to token limit]"
                    )
                    code_fence = f"```{lang_label}\n{truncated_content}\n```\n"
                    full_block = block_header + code_fence
                    block_tokens = _estimate_tokens(full_block)
                    selected_chunks.append(chunk)
                    snippet_blocks.append(full_block)
                    current_tokens += block_tokens
                    included_files.add(chunk.file_path)
                    included_symbols.add(chunk.unit_name)
                break

            selected_chunks.append(chunk)
            snippet_blocks.append(full_block)
            current_tokens += block_tokens
            included_files.add(chunk.file_path)
            included_symbols.add(chunk.unit_name)

        formatted_text = header + "".join(snippet_blocks)

        return RetrievedContext(
            formatted_text=formatted_text,
            selected_chunks=selected_chunks,
            total_tokens=current_tokens,
            included_files=sorted(included_files),
            included_symbols=sorted(included_symbols),
        )

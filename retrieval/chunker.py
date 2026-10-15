"""retrieval/chunker.py

Semantic Unit Code Chunker for RepoMind.
Parses Python, JS/TS, and configuration files into discrete semantic units
(classes, functions, methods, module overviews, config sections).
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _estimate_tokens(text: str) -> int:
    """Fast token estimator (~4 chars per token)."""
    return len(text) // 4


@dataclass
class CodeChunk:
    """Represents a single semantic code chunk."""

    chunk_id: str
    file_path: str
    unit_type: str  # "class", "function", "method", "module", "config"
    unit_name: str  # e.g., "SemanticRetriever", "retrieve", "module_overview"
    start_line: int
    end_line: int
    content: str
    docstring: str = ""
    language: str = "text"
    tokens: int = 0
    parent_symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "unit_type": self.unit_type,
            "unit_name": self.unit_name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "docstring": self.docstring,
            "language": self.language,
            "tokens": self.tokens,
            "parent_symbol": self.parent_symbol,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodeChunk:
        return cls(
            chunk_id=data["chunk_id"],
            file_path=data["file_path"],
            unit_type=data["unit_type"],
            unit_name=data["unit_name"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            content=data["content"],
            docstring=data.get("docstring", ""),
            language=data.get("language", "text"),
            tokens=data.get("tokens", _estimate_tokens(data["content"])),
            parent_symbol=data.get("parent_symbol"),
            metadata=data.get("metadata", {}),
        )


class CodeChunker:
    """Parses repository source files into structured semantic CodeChunks."""

    def __init__(self, max_chunk_lines: int = 150, min_chunk_lines: int = 3) -> None:
        self.max_chunk_lines = max_chunk_lines
        self.min_chunk_lines = min_chunk_lines

    def detect_language(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".json": "json",
            ".toml": "toml",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".md": "markdown",
            ".html": "html",
            ".css": "css",
        }
        return mapping.get(ext, "text")

    def chunk_file(self, file_path: str, content: str) -> list[CodeChunk]:
        """Chunk a single file by language-specific parser or fallback."""
        file_path_norm = file_path.replace("\\", "/")
        language = self.detect_language(file_path_norm)

        if not content.strip():
            return []

        chunks: list[CodeChunk] = []

        if language == "python":
            chunks = self._chunk_python(file_path_norm, content)
        elif language in {"json", "toml", "yaml"}:
            chunks = self._chunk_config(file_path_norm, content, language)
        elif language in {"javascript", "typescript"}:
            chunks = self._chunk_javascript(file_path_norm, content, language)

        # If no semantic chunks were extracted or for unhandled languages, use windowed chunker
        if not chunks:
            chunks = self._chunk_windowed(file_path_norm, content, language)

        return chunks

    def chunk_repository(self, files_by_path: dict[str, str]) -> list[CodeChunk]:
        """Chunk all files in a repository dictionary."""
        all_chunks: list[CodeChunk] = []
        for path, content in files_by_path.items():
            all_chunks.extend(self.chunk_file(path, content))
        return all_chunks

    def _chunk_python(self, file_path: str, content: str) -> list[CodeChunk]:
        """Use Python AST to extract module overview, classes, functions, and methods."""
        chunks: list[CodeChunk] = []
        lines = content.splitlines()
        total_lines = len(lines)

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return self._chunk_windowed(file_path, content, "python")

        # 1. Module Overview Chunk
        docstring = ast.get_docstring(tree) or ""
        header_lines: list[str] = []
        for _i, line in enumerate(lines[:30], 1):
            if line.strip().startswith(("import ", "from ", "#", '"""', "'''")):

                header_lines.append(line)
            elif not line.strip():
                continue
            else:
                break

        module_content = "\n".join(header_lines) or "\n".join(lines[:20])
        chunks.append(
            CodeChunk(
                chunk_id=f"{file_path}::module_overview::1",
                file_path=file_path,
                unit_type="module",
                unit_name=Path(file_path).stem,
                start_line=1,
                end_line=min(30, total_lines),
                content=module_content,
                docstring=docstring,
                language="python",
                tokens=_estimate_tokens(module_content),
            )
        )

        # 2. Extract Top-Level Statements and Definitions
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                chunks.extend(self._extract_python_class(file_path, lines, node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunks.append(self._extract_python_function(file_path, lines, node))

        return chunks

    def _extract_python_class(
        self, file_path: str, lines: list[str], node: ast.ClassDef
    ) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line + len(node.body))
        docstring = ast.get_docstring(node) or ""
        class_code = "\n".join(lines[start_line - 1 : end_line])

        # Class chunk itself
        chunks.append(
            CodeChunk(
                chunk_id=f"{file_path}::{node.name}::{start_line}",
                file_path=file_path,
                unit_type="class",
                unit_name=node.name,
                start_line=start_line,
                end_line=end_line,
                content=class_code,
                docstring=docstring,
                language="python",
                tokens=_estimate_tokens(class_code),
            )
        )

        # Methods inside class
        for subnode in node.body:
            if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m_start = subnode.lineno
                m_end = getattr(subnode, "end_lineno", m_start)
                m_doc = ast.get_docstring(subnode) or ""
                m_code = "\n".join(lines[m_start - 1 : m_end])
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{file_path}::{node.name}.{subnode.name}::{m_start}",
                        file_path=file_path,
                        unit_type="method",
                        unit_name=f"{node.name}.{subnode.name}",
                        start_line=m_start,
                        end_line=m_end,
                        content=m_code,
                        docstring=m_doc,
                        language="python",
                        tokens=_estimate_tokens(m_code),
                        parent_symbol=node.name,
                    )
                )

        return chunks

    def _extract_python_function(
        self, file_path: str, lines: list[str], node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> CodeChunk:
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)
        docstring = ast.get_docstring(node) or ""
        func_code = "\n".join(lines[start_line - 1 : end_line])

        return CodeChunk(
            chunk_id=f"{file_path}::{node.name}::{start_line}",
            file_path=file_path,
            unit_type="function",
            unit_name=node.name,
            start_line=start_line,
            end_line=end_line,
            content=func_code,
            docstring=docstring,
            language="python",
            tokens=_estimate_tokens(func_code),
        )

    def _chunk_javascript(self, file_path: str, content: str, language: str) -> list[CodeChunk]:
        """Extract functions, classes, and exports in JS/TS files via pattern matching."""
        chunks: list[CodeChunk] = []
        lines = content.splitlines()
        total_lines = len(lines)

        # Regex patterns for JS/TS definitions
        pattern = re.compile(
            r"^(?:export\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z0-9_$]+)"
        )

        current_name: str | None = None
        current_type: str = "function"
        current_start: int = 1
        current_lines: list[str] = []

        for i, line in enumerate(lines, 1):
            match = pattern.match(line.strip())
            if match:
                if current_name and len(current_lines) >= self.min_chunk_lines:
                    chunk_code = "\n".join(current_lines)
                    chunks.append(
                        CodeChunk(
                            chunk_id=f"{file_path}::{current_name}::{current_start}",
                            file_path=file_path,
                            unit_type=current_type,
                            unit_name=current_name,
                            start_line=current_start,
                            end_line=i - 1,
                            content=chunk_code,
                            language=language,
                            tokens=_estimate_tokens(chunk_code),
                        )
                    )
                current_name = match.group(1)
                current_type = "class" if "class" in line else "function"
                current_start = i
                current_lines = [line]
            else:
                if current_name:
                    current_lines.append(line)

        if current_name and current_lines:
            chunk_code = "\n".join(current_lines)
            chunks.append(
                CodeChunk(
                    chunk_id=f"{file_path}::{current_name}::{current_start}",
                    file_path=file_path,
                    unit_type=current_type,
                    unit_name=current_name,
                    start_line=current_start,
                    end_line=total_lines,
                    content=chunk_code,
                    language=language,
                    tokens=_estimate_tokens(chunk_code),
                )
            )

        return chunks

    def _chunk_config(self, file_path: str, content: str, language: str) -> list[CodeChunk]:
        """Extract top-level sections or key blocks in config files."""
        chunks: list[CodeChunk] = []
        lines = content.splitlines()

        if language == "json":
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    for key, val in data.items():
                        val_str = json.dumps({key: val}, indent=2)
                        chunks.append(
                            CodeChunk(
                                chunk_id=f"{file_path}::{key}::1",
                                file_path=file_path,
                                unit_type="config",
                                unit_name=key,
                                start_line=1,
                                end_line=len(val_str.splitlines()),
                                content=val_str,
                                language="json",
                                tokens=_estimate_tokens(val_str),
                            )
                        )
            except Exception:
                pass

        if not chunks:
            # Fallback TOML / YAML section chunker
            section_pattern = re.compile(r"^\[([A-Za-z0-9_.\-]+)\]|^([A-Za-z0-9_\-]+):")
            curr_section = "config_head"
            curr_start = 1
            curr_lines: list[str] = []

            for i, line in enumerate(lines, 1):
                match = section_pattern.match(line.strip())
                if match:
                    sec_name = match.group(1) or match.group(2)
                    if curr_lines:
                        code = "\n".join(curr_lines)
                        chunks.append(
                            CodeChunk(
                                chunk_id=f"{file_path}::{curr_section}::{curr_start}",
                                file_path=file_path,
                                unit_type="config",
                                unit_name=curr_section,
                                start_line=curr_start,
                                end_line=i - 1,
                                content=code,
                                language=language,
                                tokens=_estimate_tokens(code),
                            )
                        )
                    curr_section = sec_name
                    curr_start = i
                    curr_lines = [line]
                else:
                    curr_lines.append(line)

            if curr_lines:
                code = "\n".join(curr_lines)
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{file_path}::{curr_section}::{curr_start}",
                        file_path=file_path,
                        unit_type="config",
                        unit_name=curr_section,
                        start_line=curr_start,
                        end_line=len(lines),
                        content=code,
                        language=language,
                        tokens=_estimate_tokens(code),
                    )
                )

        return chunks

    def _chunk_windowed(self, file_path: str, content: str, language: str) -> list[CodeChunk]:
        """Sliding line window chunker for general/unstructured text or large blocks."""
        chunks: list[CodeChunk] = []
        lines = content.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return []

        step = max(1, self.max_chunk_lines // 2)

        for start_idx in range(0, total_lines, step):
            end_idx = min(start_idx + self.max_chunk_lines, total_lines)
            chunk_lines = lines[start_idx:end_idx]
            chunk_text = "\n".join(chunk_lines)

            chunks.append(
                CodeChunk(
                    chunk_id=f"{file_path}::block::{start_idx + 1}",
                    file_path=file_path,
                    unit_type="block",
                    unit_name=f"lines_{start_idx + 1}_{end_idx}",
                    start_line=start_idx + 1,
                    end_line=end_idx,
                    content=chunk_text,
                    language=language,
                    tokens=_estimate_tokens(chunk_text),
                )
            )
            if end_idx == total_lines:
                break

        return chunks

"""
tools/agent_runner.py

Replaces the old stub `test_executor.py`.  This is the real entry point that
`api/routes.py` calls for every job.

Flow:
  1. Clone the target repository into a temp directory.
  2. Parse every source file so the agent has full repo context.
  3. Run the AgentChain (planner → executor) with the user's instruction.
  4. Write each FileChange back to disk.
  5. Commit and push the changes to a new branch.
  6. Open a pull request and return its URL + diff summary.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from langchain_groq import ChatGroq

from agent.chain import AgentChain
from agent.executor import FileChange, ToolSpec
from agent.memory import MemoryManager
from config.settings import get_settings
from tools.code_parser import parse_repository
from tools.diff_generator import generate_repo_diff
from tools.github_tool import (
    clone_repository,
    create_branch,
    commit_changes,
    push_branch,
)
from tools.pr_tool import build_pr_title, build_pr_body, create_pull_request

logger = logging.getLogger(__name__)

# Shared memory so /refine calls on the same job_id preserve context.
_memory = MemoryManager()


def _build_tools(repo_path: Path, repo_files: dict[str, str]) -> list[ToolSpec]:
    """
    Build the ToolSpec list that the executor will choose from.

    Currently exposes a single 'code_editor' tool.  The tool receives a list
    of {filename, updated_content, reason} dicts from the executor's
    code-generation prompt and writes them into the local clone.
    """

    def code_editor(inputs: dict) -> dict:
        """
        Write one or more file changes to disk inside the cloned repo.

        Expected inputs keys:
            file_changes: list of {filename, updated_content, reason}

        Returns:
            dict with 'file_changes' (echoed back) and 'notes'.
        """
        raw_changes: list[dict] = inputs.get("file_changes", [])

        if not raw_changes:
            # Executor passes target_files + new_logic from the PlanStep —
            # generate the change list from those fields when missing.
            filename = inputs.get("filename") or inputs.get("target_file", "")
            new_content = inputs.get("updated_content") or inputs.get("new_content", "")
            reason = inputs.get("reason", "Agent-generated change")
            if filename and new_content:
                raw_changes = [
                    {"filename": filename, "updated_content": new_content, "reason": reason}
                ]

        applied: list[dict] = []
        for change in raw_changes:
            filename: str = change.get("filename", "")
            updated_content: str = change.get("updated_content", "")
            reason: str = change.get("reason", "Agent change")

            if not filename or not updated_content.strip():
                logger.warning("code_editor: skipping change with empty filename or content.")
                continue

            target = repo_path / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated_content, encoding="utf-8")
            logger.info("code_editor: wrote %s (%d bytes)", filename, len(updated_content))
            applied.append(
                {"filename": filename, "updated_content": updated_content, "reason": reason}
            )

        notes = (
            f"Wrote {len(applied)} file(s): {[c['filename'] for c in applied]}"
            if applied
            else "No files written — inputs were empty."
        )
        return {"file_changes": applied, "notes": notes}

    return [
        ToolSpec(
            name="code_editor",
            description=(
                "Writes one or more source-file changes to the cloned repository on disk. "
                "Use this tool for every step that needs to create or modify a file. "
                "Provide 'file_changes' as a list of objects, each with 'filename' "
                "(relative path from repo root), 'updated_content' (the COMPLETE new "
                "file content), and 'reason' (one-sentence explanation)."
            ),
            fn=code_editor,
        )
    ]


def run_agent(
    repo_url: str,
    instruction: str,
    session_id: str,
    branch_name: str = "repomind/auto-fix",
    pr_title_override: Optional[str] = None,
    base_branch: str = "main",
) -> dict:
    """
    Full end-to-end agent run.

    Args:
        repo_url:          GitHub HTTPS clone URL.
        instruction:       Plain-English change request from the user.
        session_id:        Job UUID — used as the memory session key.
        branch_name:       Name of the feature branch to create.
        pr_title_override: If set, overrides the auto-generated PR title.
        base_branch:       Branch to merge the PR into (default: main).

    Returns:
        {
            "pr_url":       str | None,
            "summary":      str,
            "diff_summary": str,
        }
    """
    settings = get_settings()

    with tempfile.TemporaryDirectory(prefix="repomind_") as tmp_dir:
        repo_path = Path(tmp_dir) / "repo"

        # ── 1. Clone ─────────────────────────────────────────────────────────
        logger.info("Cloning %s into %s", repo_url, repo_path)
        # Inject token for authenticated push
        authenticated_url = repo_url.replace(
            "https://",
            f"https://{settings.github_token}@",
        )
        git_repo = clone_repository(authenticated_url, repo_path)

        # ── 2. Parse repo files for context ──────────────────────────────────
        logger.info("Parsing repository files")
        repo_files_before: dict[str, str] = parse_repository(repo_path)

        # Prefix every file with its path so the LLM has unambiguous context
        file_context_lines = []
        for rel_path, content in repo_files_before.items():
            file_context_lines.append(f"\n### FILE: {rel_path}\n```\n{content}\n```")
        file_context = "\n".join(file_context_lines)

        enriched_instruction = (
            f"{instruction}\n\n" f"---\nRepository file tree and contents:\n{file_context}"
        )

        # ── 3. Build LLM + tools ──────────────────────────────────────────────
        llm = ChatGroq(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )
        tools = _build_tools(repo_path, repo_files_before)

        # ── 4. Run AgentChain ─────────────────────────────────────────────────
        logger.info("Running AgentChain for session %s", session_id)
        chain = AgentChain(llm=llm, tools=tools, memory=_memory)
        result = chain.run(session_id=session_id, instruction=enriched_instruction)

        if not result.execution.all_file_changes:
            logger.warning("Agent produced no file changes for session %s", session_id)
            return {
                "pr_url": None,
                "summary": "Agent completed but made no file changes.",
                "diff_summary": "",
            }

        # ── 5. Create branch + commit ─────────────────────────────────────────
        logger.info("Creating branch '%s'", branch_name)
        create_branch(git_repo, branch_name)

        commit_msg = f"feat: {instruction[:100].strip()}"
        commit_sha = commit_changes(git_repo, commit_msg)
        if commit_sha is None:
            logger.warning("Nothing to commit — all writes may have been no-ops.")
            return {
                "pr_url": None,
                "summary": "Files were generated but no disk changes detected.",
                "diff_summary": "",
            }

        # ── 6. Push ───────────────────────────────────────────────────────────
        logger.info("Pushing branch '%s'", branch_name)
        push_branch(git_repo, branch_name=branch_name)

        # ── 7. Build diff summary ─────────────────────────────────────────────
        repo_files_after: dict[str, str] = parse_repository(repo_path)
        per_file_diffs: dict[str, str] = generate_repo_diff(repo_files_before, repo_files_after)

        changed_file_names = [c.filename for c in result.execution.all_file_changes]
        lines_added = sum(d.count("\n+") for d in per_file_diffs.values())
        lines_removed = sum(d.count("\n-") for d in per_file_diffs.values())
        diff_summary_text = (
            f"Modified {len(changed_file_names)} file(s), "
            f"+{lines_added} lines, -{lines_removed} lines."
        )

        # ── 8. Open pull request ──────────────────────────────────────────────
        # Extract owner/repo from URL e.g. https://github.com/owner/repo(.git)
        repo_full_name = (
            repo_url.replace("https://github.com/", "").rstrip("/").removesuffix(".git")
        )

        pr_title = pr_title_override or build_pr_title(instruction)
        pr_body = build_pr_body(
            instruction=instruction,
            changed_files=changed_file_names,
            diff_summary=per_file_diffs,
        )

        logger.info("Opening PR on %s", repo_full_name)
        pr = create_pull_request(
            token=settings.github_token,
            repo_full_name=repo_full_name,
            title=pr_title,
            body=pr_body,
            head_branch=branch_name,
            base_branch=base_branch,
        )

        logger.info("PR opened: %s", pr.html_url)
        return {
            "pr_url": pr.html_url,
            "summary": diff_summary_text,
            "diff_summary": diff_summary_text,
        }

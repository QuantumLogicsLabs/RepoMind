"""
Real agent executor — replaces the stub that returned a hardcoded fake PR URL.

Called by api/routes.py → process_job() for every job.
"""

from __future__ import annotations

import os
import re
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

from langchain_groq import ChatGroq

from agent.chain import AgentChain
from agent.executor import ToolSpec
from tools.code_parser import parse_repository
from tools.diff_generator import generate_repo_diff
from tools.github_tool import create_branch, commit_changes
from tools.pr_tool import create_pull_request, build_pr_title, build_pr_body
from config.settings import get_settings


def run_test_executor(repo_url: str, instruction: str) -> dict:
    """
    Full agent pipeline:
      1. Clone the target repo
      2. Run the LangChain agent to apply the instruction
      3. Commit & push changes to a new branch
      4. Open a real GitHub PR
      5. Return {"pr_url": "...", "summary": "..."}
    """
    settings = get_settings()

    # ── 1. Build branch name from the instruction ─────────────────────────────
    slug = instruction.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")[:50]
    branch_name = f"repomind/{slug or 'update'}"

    # ── 2. Set up git credential env (used for both clone and push) ───────────
    askpass_env = {
        **os.environ,
        "GIT_USERNAME": settings.github_username,
        "GIT_PASSWORD": settings.github_token,
    }

    # ── 3. Clone repo into a temp directory ───────────────────────────────────
    tmpdir = tempfile.mkdtemp(prefix="repomind_")
    local_path = Path(tmpdir) / "repo"

    # Write the askpass helper so git can get credentials without them being
    # embedded in the URL (which GitPython strips on push anyway)
    askpass_path = Path(tmpdir) / "askpass.py"
    askpass_path.write_text(
        "import os, sys\n"
        "prompt = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if 'username' in prompt.lower():\n"
        "    print(os.environ['GIT_USERNAME'])\n"
        "else:\n"
        "    print(os.environ['GIT_PASSWORD'])\n",
        encoding="utf-8",
    )
    askpass_env["GIT_ASKPASS"] = f"{sys.executable} {askpass_path}"

    try:
        # Clone via subprocess so askpass env applies
        subprocess.run(
            ["git", "clone", repo_url, str(local_path)],
            env=askpass_env,
            check=True,
            capture_output=True,
            text=True,
        )
        from git import Repo as GitRepo

        repo = GitRepo(str(local_path))
        create_branch(repo, branch_name)

        # ── 4. Parse the repo so the agent has context ────────────────────────
        parsed_files = parse_repository(local_path)
        old_files = dict(parsed_files)  # snapshot before edits

        # ── 5. Build tools for the agent ──────────────────────────────────────
        def _write_file(inputs: dict) -> dict:
            """Tool the agent calls to write/update a file."""
            file_path = inputs.get("filename") or inputs.get("file_path", "")
            content = inputs.get("updated_content") or inputs.get("content", "")
            target = local_path / file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {
                "file_changes": [
                    {"filename": file_path, "updated_content": content, "reason": "Agent edit"}
                ],
                "notes": f"Wrote {file_path}",
            }

        tools = [
            ToolSpec(
                name="write_file",
                description=(
                    "Write or update a file in the repository. "
                    "Inputs: filename (relative path), updated_content (full new content)."
                ),
                fn=_write_file,
            )
        ]

        # ── 6. Run the agent chain ─────────────────────────────────────────────
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",  # fast, free-tier Groq model
            groq_api_key=settings.groq_api_key,
            temperature=0,
        )
        chain = AgentChain(llm=llm, tools=tools)
        chain_result = chain.run(
            session_id=branch_name,
            instruction=f"{instruction}\n\nRepo files:\n"
            + "\n".join(f"=== {p} ===\n{c}" for p, c in parsed_files.items()),
        )

        # ── 7. Compute diff ───────────────────────────────────────────────────
        new_files = parse_repository(local_path)
        diffs = generate_repo_diff(old_files, new_files)
        changed = list(diffs.keys())

        if not changed:
            return {
                "pr_url": None,
                "summary": "Agent completed but made no file changes.",
            }

        # ── 8. Commit & push ──────────────────────────────────────────────────
        # Use subprocess with GIT_ASKPASS so credentials are never embedded in
        # the URL (GitPython strips token-in-URL auth during push on Windows).
        commit_changes(repo, f"repomind: {instruction[:72]}")

        push_result = subprocess.run(
            ["git", "push", "--force", "origin", f"{branch_name}:{branch_name}"],
            cwd=str(local_path),
            env=askpass_env,
            capture_output=True,
            text=True,
        )
        if push_result.returncode != 0:
            raise RuntimeError(f"Failed to push branch '{branch_name}':\n{push_result.stderr}")

        # ── 9. Open the PR ────────────────────────────────────────────────────
        repo_full_name = (
            repo_url.rstrip("/").replace("https://github.com/", "").removesuffix(".git")
        )
        pr_title = build_pr_title(instruction)
        pr_body = build_pr_body(
            instruction=instruction,
            changed_files=changed,
            diff_summary=diffs,
        )
        pr = create_pull_request(
            token=settings.github_token,
            repo_full_name=repo_full_name,
            title=pr_title,
            body=pr_body,
            head_branch=branch_name,
            base_branch="main",
        )

        summary = f"Modified {len(changed)} file(s): {', '.join(changed[:5])}" + (
            " …" if len(changed) > 5 else ""
        )

        return {"pr_url": pr.html_url, "summary": summary}

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

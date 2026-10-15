"""tools/agent_runner.py

Replaces the old stub `test_executor.py`. This is the real entry point that
`api/routes.py` calls for every job.

Flow:
  1. Clone the target repository into a temp directory.
  2. Parse every source file so the agent has full repo context.
  3. Run the AgentChain (planner -> executor) with the user's instruction.
  4. Write each FileChange back to disk.
  5. Commit and push the changes to a new branch.
  6. Open a pull request and return its URL + diff summary.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from pydantic import SecretStr

from agent.chain import AgentChain
from agent.executor import ToolSpec
from agent.memory import MemoryManager
from agent.plugin import plugin_manager
from config.settings import get_settings
from tools.code_graph import CodeGraph, build_code_graph, update_file_in_graph
from tools.code_parser import (
    build_project_map,
    get_project_readme,
    parse_repository,
    parse_repository_full,
)
from tools.diff_generator import generate_repo_diff
from tools.github_tool import (
    clone_repository,
    commit_changes,
    create_branch,
    push_branch,
)
from tools.pr_tool import build_pr_body, build_pr_title, create_pull_request
from utils.job_manager import job_manager
from utils.logging import get_logger
from utils.metrics import metrics_collector

logger = get_logger("tools.agent_runner")

_memory = MemoryManager()


_FINALISE_SYSTEM_PROMPT = (
    "You are RepoMind, an expert senior software engineer finishing ONE file of a "
    "multi-file change. You are given the file's CURRENT content (empty if it is new), "
    "a DRAFT of what the change should contain, the REASON for the change, and the "
    "other files already written in this change.\n\n"
    "RULES:\n"
    "1. Output the COMPLETE final file and nothing else: no markdown fences, no commentary.\n"
    "2. If the file already has content, keep it unless the change replaces it. Never drop "
    "unrelated sections, code or configuration.\n"
    "3. Treat the draft as intent. Fix and improve it. Never leave placeholders or TODOs.\n"
    "4. Stay consistent with the other files: reuse the exact ids, classes, function names "
    "and paths they define, and only link to files that exist or are created in this change.\n"
    "5. Write in the language of the file. For web pages: semantic HTML, responsive CSS "
    "(include a mobile breakpoint), accessible markup, a viewport meta tag and working "
    "in-page anchors.\n"
    "6. Web copy must be substantial: every section gets real, well-written paragraphs "
    "and concrete items (for example, each program gets a name, a short description "
    "and who it is for). Never ship a one-line section or lorem ipsum.\n"
    "7. Use only facts from the user's request. Where facts are thin, expand with "
    "truthful general framing (what the work is, who it helps, how it works). Do NOT "
    "invent statistics, names, dates, addresses, partners, testimonials, legal status, "
    "accreditation or claims about who built or reviews the content. Where the request "
    "names no concrete items (such as which programs exist), give a few clearly "
    "illustrative examples. For contact details use an obvious placeholder such as "
    "hello@example.org. Never hard-code the current year; compute it in JavaScript.\n"
    "8. For Python: valid syntax, existing style, meaningful docstrings, real type hints."
)

_FINALISE_HUMAN_PROMPT = (
    "File: {filename}\n\n"
    "Current content:\n---\n{current_content}\n---\n\n"
    "Draft of the change:\n---\n{draft}\n---\n\n"
    "Overall user request (the whole change):\n{request}\n\n"
    "Reason for this file: {reason}\n\n"
    "Other files in this change:\n{siblings}\n\n"
    "Return the complete final content of {filename} only."
)

_MAX_CONTEXT_CHARS = 30_000
_MAX_SIBLING_CHARS = 6_000


def _normalise_changes(raw_changes: object) -> list[dict]:
    """Coerce the model's ``file_changes`` argument into a list of dicts.

    Models sometimes send a single dict, a JSON string, or a list that mixes
    objects and JSON strings. Anything that cannot be understood is dropped.
    """
    if isinstance(raw_changes, (str, dict)):
        raw_changes = [raw_changes]
    if not isinstance(raw_changes, list):
        return []

    changes: list[dict] = []
    for item in raw_changes:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except ValueError:
                logger.warning("code_editor: ignoring unparseable file change: %.80s", item)
                continue
        if isinstance(item, dict):
            changes.append(item)
        else:
            logger.warning("code_editor: ignoring file change of type %s.", type(item).__name__)
    return changes


def _line_retention(old: str, new: str) -> float:
    """Fraction of the old file's non-blank lines that are still present in the new one."""
    old_lines = [line.strip() for line in old.splitlines() if line.strip()]
    if not old_lines:
        return 1.0
    new_lines = {line.strip() for line in new.splitlines()}
    return sum(line in new_lines for line in old_lines) / len(old_lines)


def _finalise_file(
    llm_api_key: str,
    filename: str,
    current_content: str,
    draft: str,
    reason: str,
    siblings: dict[str, str],
    request: str = "",
) -> str:
    """Ask the LLM for the final content of one file, or "" if that fails."""
    sibling_text = (
        "\n\n".join(
            f"=== {name} ===\n{body[:_MAX_SIBLING_CHARS]}"
            for name, body in siblings.items()
            if name != filename
        )
        or "(none yet)"
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", _FINALISE_SYSTEM_PROMPT), ("human", _FINALISE_HUMAN_PROMPT)]
    )
    llm = ChatGroq(
        model=get_settings().llm_model,
        api_key=SecretStr(llm_api_key),  # already rotated/resolved by resolve_llm_credentials()
        temperature=0,
    )
    try:
        response = (prompt | llm).invoke(
            {
                "filename": filename,
                "current_content": current_content[:_MAX_CONTEXT_CHARS] or "(empty: new file)",
                "draft": draft[:_MAX_CONTEXT_CHARS] or "(no draft: write it from the reason)",
                "reason": reason or "Improve this file",
                "request": request or "(not provided)",
                "siblings": sibling_text,
            }
        )
    except Exception:  # noqa: BLE001 - fall back to the model's own draft
        logger.exception("code_editor: finalising %s failed; using the draft.", filename)
        return ""

    content = response.content
    text = content if isinstance(content, str) else "\n".join(str(item) for item in content)
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return text.strip() + "\n" if text.strip() else ""


def _build_tools(
    repo_path: Path,
    repo_files: dict[str, str],
    llm_api_key: str,
    code_graph: CodeGraph | None = None,
    instruction: str = "",
) -> list[ToolSpec]:
    """Build the ToolSpec list that the executor will choose from."""
    written_this_run: dict[str, str] = {}

    def code_editor(inputs: dict) -> dict:
        raw_changes = _normalise_changes(inputs.get("file_changes", []))

        if not raw_changes:
            filename = inputs.get("filename") or inputs.get("target_file", "")
            new_content = inputs.get("updated_content") or inputs.get("new_content", "")
            reason = inputs.get("reason", "Agent-generated change")
            if filename and new_content:
                raw_changes = [
                    {"filename": filename, "updated_content": new_content, "reason": reason}
                ]

        applied: list[dict] = []
        for change in raw_changes:
            change_filename = str(change.get("filename", ""))
            updated_content = change.get("updated_content", "")

            if not isinstance(updated_content, str):
                updated_content = str(updated_content)

            change_reason = str(change.get("reason", "Agent change"))

            if not change_filename or not updated_content.strip():
                logger.warning("code_editor: skipping change with empty filename or content.")
                continue

            target = (repo_path / change_filename).resolve()
            if not target.is_relative_to(repo_path.resolve()):
                logger.warning("code_editor: refusing to write outside repo: %s", change_filename)
                continue

            current_content = target.read_text(encoding="utf-8") if target.exists() else ""
            placeholder_signals = [
                "Add content here",
                "Add updated content",
                "update this with",
                "insert here",
            ]
            is_placeholder = bool(re.search(r"\bTODO\b", updated_content)) or any(
                signal.lower() in updated_content.lower() for signal in placeholder_signals
            )

            # The model that chose this tool never saw the existing file or the
            # other files in this change, so its draft can clobber existing
            # content or disagree with sibling files (ids, classes, paths). A
            # final generation pass sees all of that and writes the real file.
            logger.info("code_editor: finalising %s with the LLM.", change_filename)
            finalised = _finalise_file(
                llm_api_key=llm_api_key,
                filename=change_filename,
                current_content=current_content,
                draft="" if is_placeholder else updated_content,
                reason=change_reason,
                siblings=written_this_run,
                request=instruction,
            )
            if finalised:
                updated_content = finalised

            if current_content.strip() and _line_retention(current_content, updated_content) < 0.5:
                logger.warning(
                    "code_editor: %s dropped most of its existing content; retrying once.",
                    change_filename,
                )
                retried = _finalise_file(
                    llm_api_key=llm_api_key,
                    filename=change_filename,
                    current_content=current_content,
                    draft=updated_content,
                    reason=(
                        f"{change_reason}\nIMPORTANT: a previous attempt deleted existing content. "
                        "Keep EVERY existing line of the current file exactly as it is and only "
                        "add or change what this change needs."
                    ),
                    siblings=written_this_run,
                    request=instruction,
                )
                if retried and _line_retention(current_content, retried) >= 0.5:
                    updated_content = retried
                else:
                    logger.warning(
                        "code_editor: %s still loses existing content; keeping the original.",
                        change_filename,
                    )
                    continue
            written_this_run[change_filename] = updated_content

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated_content, encoding="utf-8")

            if code_graph is not None and change_filename.endswith(".py"):
                update_file_in_graph(code_graph, change_filename, updated_content, repo_files)
                repo_files[change_filename] = updated_content

            logger.info(
                "code_editor: wrote %s (%d bytes)",
                change_filename,
                len(updated_content),
            )
            applied.append(
                {
                    "filename": change_filename,
                    "updated_content": updated_content,
                    "reason": change_reason,
                }
            )

        notes = (
            f"Wrote {len(applied)} file(s): {[c['filename'] for c in applied]}"
            if applied
            else "No files written — inputs were empty."
        )
        return {"file_changes": applied, "notes": notes}

    def code_editor_precondition(step, repo_context):
        """code_editor needs at least one target file, and — if repo state is
        available — every target file must be a real path under the repo
        (not an attempt to escape it via '..').
        """
        from agent.executor import PreconditionResult

        if not step.target_files:
            return PreconditionResult(ok=False, reason="Step has no target_files specified.")
        for target_file in step.target_files:
            if ".." in target_file.replace("\\", "/").split("/"):
                return PreconditionResult(
                    ok=False,
                    reason=f"target_file '{target_file}' attempts to escape the repo root.",
                )
        return PreconditionResult(ok=True)

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
            capabilities=["edit_file", "create_file"],
            precondition=code_editor_precondition,
        )
    ]


def validate_credentials(github_token: str, llm_provider: str, llm_api_key: str) -> None:
    """
    Verify GitHub and LLM credentials actually work before starting a job.

    Fails fast with a clear, non-sensitive error message instead of letting
    the job fail partway through (e.g. after a slow clone).

    Raises:
        ValueError: If either credential is invalid or unreachable.
    """
    # 1. Validate GitHub token via a lightweight authenticated request.
    try:
        response = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {github_token}"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise ValueError(f"Could not reach GitHub API to validate token: {exc}") from None

    if response.status_code == 401:
        raise ValueError("GitHub token is invalid or expired.")
    if response.status_code != 200:
        raise ValueError(f"GitHub token validation failed (status {response.status_code}).")

    # 2. Validate the LLM key with a minimal, cheap call.
    if llm_provider == "groq":
        try:
            probe_llm = ChatGroq(
                model=get_settings().llm_model,
                api_key=SecretStr(llm_api_key),
                temperature=0,
            )
            probe_llm.invoke("ping")
        except Exception as exc:
            raise ValueError(
                f"LLM credential validation failed for provider 'groq': {exc}"
            ) from None
    else:
        # Other providers (openai, gemini) can be validated the same way
        # once their client construction is added below.
        logger.info("Skipping live LLM validation for provider '%s' (not yet wired).", llm_provider)


def run_agent(
    repo_url: str,
    instruction: str,
    session_id: str,
    branch_name: str = "repomind/auto-fix",
    pr_title_override: str | None = None,
    base_branch: str = "main",
    github_pat: str | None = None,
    llm_provider_override: str | None = None,
    llm_api_key: str | None = None,
) -> dict:
    """Full end-to-end agent run.

    Returns:
        {
            "pr_url":       str | None,
            "summary":      str,
            "diff_summary": str,
        }
    """
    settings = get_settings()
    runner_start_time = time.perf_counter()

    # Resolve request-scoped credentials, falling back to server defaults.
    # Plain strings are held only in local variables for this job's duration
    # never stored on settings, never logged.
    resolved_token = settings.resolve_github_token(SecretStr(github_pat) if github_pat else None)
    resolved_provider, resolved_llm_key = settings.resolve_llm_credentials(
        llm_provider_override,
        SecretStr(llm_api_key) if llm_api_key else None,
    )

    # Validate before doing any real work — fail fast, not partway through.
    validate_credentials(resolved_token, resolved_provider, resolved_llm_key)

    with tempfile.TemporaryDirectory(prefix="repomind_", ignore_cleanup_errors=True) as tmp_dir:
        repo_path = Path(tmp_dir) / "repo"

        # 1. Clone
        logger.info("Cloning %s into %s", repo_url, repo_path)
        job_manager.add_event(
            job_id=session_id,
            stage="cloning",
            message=f"Cloning repository {repo_url}...",
            progress=10.0,
        )
        authenticated_url = repo_url.replace(
            "https://",
            f"https://{resolved_token}@",
        )
        git_repo = clone_repository(authenticated_url, repo_path)

        # 2. Parse repo files intelligently
        logger.info("Parsing repository files")
        job_manager.add_event(
            job_id=session_id,
            stage="parsing",
            message="Analyzing repository files and building project map...",
            progress=25.0,
        )
        # Pass the instruction as a target hint to prioritize files
        project_map = build_project_map(repo_path, target_hints=[instruction])
        readme_generated = False

        generated_readme = get_project_readme(project_map)
        if generated_readme:
            readme_path = repo_path / "README.md"
            readme_path.write_text(generated_readme, encoding="utf-8")
            logger.info("Generated README.md from repository analysis")
            readme_generated = True
            # Rebuild map to include the new README
            project_map = build_project_map(repo_path, target_hints=[instruction])

        # Rely purely on the project_map and memory optimizations
        repo_files_for_agent = project_map["files"]
        repo_files_before = repo_files_for_agent.copy()

        # 2b. Build the structural code knowledge graph (functions, classes,
        # calls, inheritance, imports). Uses parse_repository_full — unlike
        # project_map, the graph needs complete repo coverage, not a
        # token-budgeted subset, so impact/traversal queries stay accurate.
        logger.info("Building code knowledge graph")
        job_manager.add_event(
            job_id=session_id,
            stage="graph_building",
            message="Building code knowledge graph (functions, classes, relationships)...",
            progress=35.0,
        )
        full_repo_files = parse_repository_full(repo_path)
        code_graph = build_code_graph(full_repo_files)

        # 3. Discover and register plugins
        if settings.plugins_dir:
            plugin_manager.discover_plugins(settings.plugins_dir)
        for ep in settings.enabled_plugins:
            try:
                if ep.endswith(".py"):
                    plugin_manager.load_plugin_from_path(ep)
                else:
                    plugin_manager.load_plugin_by_name(ep)
            except Exception as exc:
                logger.error("Failed to load enabled plugin '%s': %s", ep, exc, exc_info=exc)

        # 4. Build LLM + tools
        llm = ChatGroq(
            model=settings.llm_model,
            api_key=SecretStr(
                resolved_llm_key
            ),  # already rotated/resolved by resolve_llm_credentials()
            temperature=0,
        )
        tools = _build_tools(
            repo_path, repo_files_for_agent, resolved_llm_key, code_graph, instruction
        )

        # 4. Run AgentChain
        logger.info("Running AgentChain for session %s", session_id)
        job_manager.add_event(
            job_id=session_id,
            stage="planning",
            message="Generating execution plan with TaskPlanner...",
            progress=40.0,
        )
        chain = AgentChain(llm=llm, tools=tools, memory=_memory)
        result = chain.run_with_project_map(
            session_id=session_id,
            instruction=instruction,
            project_map=project_map,
            code_graph=code_graph,
        )

        if not result.execution.all_file_changes and not readme_generated:
            logger.warning("Agent produced no file changes for session %s", session_id)
            job_manager.add_event(
                job_id=session_id,
                stage="failed",
                message="Agent completed execution but produced no file changes.",
                progress=100.0,
            )
            return {
                "pr_url": None,
                "summary": "Agent completed but made no file changes.",
                "diff_summary": "",
            }

        # 5. Create branch + commit
        logger.info("Creating branch '%s'", branch_name)
        job_manager.add_event(
            job_id=session_id,
            stage="committing",
            message=f"Creating branch '{branch_name}' and committing file changes...",
            progress=85.0,
        )
        create_branch(git_repo, branch_name)

        commit_msg = f"feat: {instruction[:100].strip()}"
        commit_sha = commit_changes(git_repo, commit_msg)
        if commit_sha is None:
            logger.warning("Nothing to commit — all writes may have been no-ops.")
            job_manager.add_event(
                job_id=session_id,
                stage="failed",
                message="Files were generated but no disk changes were detected.",
                progress=100.0,
            )
            return {
                "pr_url": None,
                "summary": "Files were generated but no disk changes detected.",
                "diff_summary": "",
            }

        # 6. Push
        logger.info("Pushing branch '%s'", branch_name)
        job_manager.add_event(
            job_id=session_id,
            stage="pushing",
            message=f"Pushing branch '{branch_name}' to remote repository...",
            progress=90.0,
        )
        push_branch(git_repo, branch_name=branch_name)

        # 7. Build diff summary
        repo_files_after: dict[str, str] = parse_repository(repo_path)
        per_file_diffs: dict[str, str] = generate_repo_diff(repo_files_before, repo_files_after)

        changed_file_names = [c.filename for c in result.execution.all_file_changes]
        lines_added = sum(d.count("\n+") for d in per_file_diffs.values())
        lines_removed = sum(d.count("\n-") for d in per_file_diffs.values())
        diff_summary_text = (
            f"Modified {len(changed_file_names)} file(s), "
            f"+{lines_added} lines, -{lines_removed} lines."
        )

        # 8. Open pull request
        repo_full_name = (
            repo_url.replace("https://github.com/", "").rstrip("/").removesuffix(".git")
        )

        pr_title = pr_title_override or build_pr_title(instruction)
        pr_body = build_pr_body(
            instruction=instruction,
            changed_files=changed_file_names,
            diff_summary=per_file_diffs,
            impact_report=result.impact_report,
        )

        logger.info("Opening PR on %s", repo_full_name)
        job_manager.add_event(
            job_id=session_id,
            stage="pr_opening",
            message=f"Opening Pull Request: '{pr_title}'...",
            progress=95.0,
        )
        pr = create_pull_request(
            token=resolved_token,
            repo_full_name=repo_full_name,
            title=pr_title,
            body=pr_body,
            head_branch=branch_name,
            base_branch=base_branch,
        )

        logger.info("PR opened: %s", pr.html_url)
        runner_duration_sec = time.perf_counter() - runner_start_time
        metrics_collector.record_duration("run_agent_duration_seconds", runner_duration_sec)
        logger.info(
            "Agent run completed successfully",
            extra={
                "event": "run_agent_complete",
                "session_id": session_id,
                "duration_ms": round(runner_duration_sec * 1000, 2),
            },
        )
        job_manager.add_event(
            job_id=session_id,
            stage="completed",
            message=f"Pull Request created successfully! {pr.html_url}",
            progress=100.0,
            data={"pr_url": pr.html_url, "diff_summary": diff_summary_text},
        )
        return {
            "pr_url": pr.html_url,
            "summary": diff_summary_text,
            "diff_summary": diff_summary_text,
            "diff": "\n\n".join(per_file_diffs.values()),
        }


def run_agent_batch(
    repos: list[dict],
    session_id_prefix: str,
    max_workers: int = 4,
    base_branch: str = "main",
) -> dict:
    """
    Run the agent against multiple repositories concurrently.

    Each repo is processed independently via run_agent(), on its own thread,
    with its own isolated temp directory (already guaranteed by run_agent's
    use of tempfile.TemporaryDirectory) and its own session_id (so agent
    memory does not cross-contaminate between repos, even under concurrent
    execution — see MemoryManager's per-session locking).

    A failure in one repo does not stop or affect the others: each result
    is captured independently and the batch always returns a complete
    per-repo breakdown, never raises for an individual repo's failure.

    Args:
        repos: List of dicts, each with:
            - "repo_url" (str, required)
            - "instruction" (str, required)
            - "branch_name" (str, optional)
            - "pr_title_override" (str, optional)
            - "github_pat" (str, optional)
            - "llm_provider_override" (str, optional)
            - "llm_api_key" (str, optional)
        session_id_prefix: Prefix used to build a unique session_id per repo,
            e.g. "batch-<batch_id>". Each repo gets "<prefix>-<index>".
        max_workers: Maximum number of repos processed concurrently.
        base_branch: Base branch for all PRs in this batch (applies to every
            repo unless overridden per-repo in the future).

    Returns:
        {
            "total": int,
            "succeeded": int,
            "failed": int,
            "results": [
                {
                    "repo_url": str,
                    "session_id": str,
                    "status": "completed" | "failed",
                    "pr_url": str | None,
                    "summary": str,
                    "error_message": str | None,
                },
                ...
            ],
        }
    """
    batch_start_time = time.perf_counter()
    logger.info(
        "Starting batch agent run",
        extra={"event": "batch_run_start", "repo_count": len(repos)},
    )

    def _run_one(index: int, repo_spec: dict) -> dict:
        """Run a single repo's job and normalise the outcome into a dict,
        catching any exception so it never propagates out of the thread.
        """
        repo_url = repo_spec["repo_url"]
        instruction = repo_spec["instruction"]
        session_id = f"{session_id_prefix}-{index}"

        try:
            result = run_agent(
                repo_url=repo_url,
                instruction=instruction,
                session_id=session_id,
                branch_name=repo_spec.get("branch_name", "repomind/auto-fix"),
                pr_title_override=repo_spec.get("pr_title_override"),
                base_branch=base_branch,
                github_pat=repo_spec.get("github_pat"),
                llm_provider_override=repo_spec.get("llm_provider_override"),
                llm_api_key=repo_spec.get("llm_api_key"),
            )
            pr_url = result.get("pr_url")
            return {
                "repo_url": repo_url,
                "session_id": session_id,
                "status": "completed" if pr_url else "failed",
                "pr_url": pr_url,
                "summary": result.get("summary", ""),
                "error_message": None if pr_url else result.get("summary"),
            }
        except Exception as exc:
            logger.error(
                "Batch item failed",
                exc_info=exc,
                extra={
                    "event": "batch_item_failed",
                    "repo_url": repo_url,
                    "session_id": session_id,
                    "exception_type": type(exc).__name__,
                },
            )
            metrics_collector.record_failure(f"BatchItemException:{type(exc).__name__}", str(exc))
            return {
                "repo_url": repo_url,
                "session_id": session_id,
                "status": "failed",
                "pr_url": None,
                "summary": "",
                "error_message": str(exc),
            }

    results: list[dict] = [None] * len(repos)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index: dict[Future, int] = {
            executor.submit(_run_one, i, repo_spec): i for i, repo_spec in enumerate(repos)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            results[index] = future.result()

    succeeded = sum(1 for r in results if r["status"] == "completed")
    failed = len(results) - succeeded

    batch_duration_sec = time.perf_counter() - batch_start_time
    metrics_collector.record_duration("run_agent_batch_duration_seconds", batch_duration_sec)
    logger.info(
        "Batch agent run completed",
        extra={
            "event": "batch_run_complete",
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "duration_ms": round(batch_duration_sec * 1000, 2),
        },
    )

    return {
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }

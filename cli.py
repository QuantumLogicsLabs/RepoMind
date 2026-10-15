#!/usr/bin/env python3
"""
cli.py — Command-line entry point for RepoMind.

Runs the full agent pipeline — clone, plan, edit, commit, push, and open a
pull request — from a single terminal command.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import uuid

from tools.agent_runner import run_agent
from utils.job_manager import job_manager


def _print_event(event: dict) -> None:
    stage = event.get("stage", "")
    message = event.get("message", "")
    progress = event.get("progress", 0)
    print(f"[{progress:5.1f}%] {stage:12s} — {message}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Give RepoMind a repo + an instruction; it opens a PR."
    )
    parser.add_argument(
        "--repo", required=True, help="GitHub repo URL, e.g. https://github.com/owner/repo"
    )
    parser.add_argument(
        "--instruction", required=True, help="Plain-English description of the change to make"
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Branch name to create for the change (default: repomind/auto-<random>)",
    )
    parser.add_argument(
        "--base", default="main", help="Base branch to open the PR against (default: main)"
    )
    parser.add_argument("--pr-title", default=None, help="Override the auto-generated PR title")
    parser.add_argument(
        "--github-token",
        default=None,
        help="Override GITHUB_TOKEN from the environment for this run only",
    )
    parser.add_argument(
        "--llm-api-key",
        default=None,
        help="Override GROQ_API_KEY from the environment for this run only",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    branch_name = args.branch or f"repomind/auto-{uuid.uuid4().hex[:8]}"

    job_id = job_manager.create_job(repo_url=args.repo, instruction=args.instruction)

    print(f"Job:         {job_id}")
    print(f"Repo:        {args.repo}")
    print(f"Instruction: {args.instruction}")
    print(f"Branch:      {branch_name}")
    print(f"Base:        {args.base}")
    print("-" * 60)

    result_box: dict = {}
    error_box: dict = {}

    def _worker() -> None:
        try:
            result_box["result"] = run_agent(
                repo_url=args.repo,
                instruction=args.instruction,
                session_id=job_id,
                branch_name=branch_name,
                pr_title_override=args.pr_title,
                base_branch=args.base,
                github_pat=args.github_token,
                llm_api_key=args.llm_api_key,
            )
        except Exception as exc:  # noqa: BLE001
            error_box["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    printed = 0
    while worker.is_alive():
        job = job_manager.get(job_id)
        for event in job.events[printed:]:
            _print_event(event)
        printed = len(job.events)
        time.sleep(0.5)

    job = job_manager.get(job_id)
    for event in job.events[printed:]:
        _print_event(event)

    if "error" in error_box:
        print(f"\n❌ Agent run failed: {error_box['error']}", file=sys.stderr)
        return 1

    result = result_box.get("result", {})
    pr_url = result.get("pr_url")

    print()
    if not pr_url:
        print(f"⚠️  No PR opened: {result.get('summary')}")
        return 1

    print(f"✅ Pull request opened: {pr_url}")
    print(f"   {result.get('summary')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

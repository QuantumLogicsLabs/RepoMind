"""utils/metrics.py

Execution metrics collector for RepoMind.

Tracks job lifecycle counters, tool invocation stats, plan generation counts,
step execution metrics, HTTP request counters, and execution durations.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from utils.logging import get_logger

logger = get_logger("utils.metrics")


class MetricsCollector:
    """Thread-safe metrics collector for recording execution metrics across RepoMind."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job_counters: dict[str, int] = defaultdict(int)
        self._tool_counters: dict[str, int] = defaultdict(int)
        self._tool_outcome_counters: dict[str, int] = defaultdict(int)
        self._tool_selection_counters: dict[str, int] = defaultdict(int)
        self._http_request_counters: dict[str, int] = defaultdict(int)
        self._failure_counters: dict[str, int] = defaultdict(int)
        self._durations: dict[str, list[float]] = defaultdict(list)
        self._total_plans: int = 0
        self._total_steps_generated: int = 0
        self._total_steps_executed: int = 0
        self._total_steps_retried: int = 0
        self._total_file_changes: int = 0

    def record_job_created(self) -> None:
        """Record job creation metric."""
        with self._lock:
            self._job_counters["total"] += 1
            self._job_counters["queued"] += 1

    def record_job_status_change(self, old_status: str, new_status: str) -> None:
        """Record job status transition."""
        with self._lock:
            if old_status in self._job_counters and self._job_counters[old_status] > 0:
                self._job_counters[old_status] -= 1
            self._job_counters[new_status] += 1
            logger.debug(
                "Job metric recorded",
                extra={
                    "event": "metric_job_status",
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )

    def record_tool_execution(self, tool_name: str, outcome: str = "success") -> None:
        """Record tool invocation metric."""
        with self._lock:
            self._tool_counters[tool_name] += 1
            self._tool_outcome_counters[outcome] += 1
            logger.debug(
                "Tool execution metric recorded",
                extra={"event": "metric_tool_exec", "tool_name": tool_name, "outcome": outcome},
            )

    def record_tool_selection(
        self, original_tool_name: str, resolved_tool_name: str, used_fallback: bool
    ) -> None:
        """
        Record whether the planner/executor's first tool choice was usable,
        or whether a fallback tool had to be substituted — the basis for
        selection-accuracy metrics (goal: measure tool-selection accuracy
        and unnecessary tool usage).
        """
        with self._lock:
            self._tool_selection_counters["total"] += 1
            if used_fallback:
                self._tool_selection_counters["fallback_used"] += 1
            else:
                self._tool_selection_counters["first_choice_accepted"] += 1
            logger.debug(
                "Tool selection metric recorded",
                extra={
                    "event": "metric_tool_selection",
                    "original_tool_name": original_tool_name,
                    "resolved_tool_name": resolved_tool_name,
                    "used_fallback": used_fallback,
                },
            )

    def record_plan_generated(self, step_count: int) -> None:
        """Record plan generation metrics."""
        with self._lock:
            self._total_plans += 1
            self._total_steps_generated += step_count
            logger.debug(
                "Plan metric recorded",
                extra={"event": "metric_plan_gen", "step_count": step_count},
            )

    def record_step_executed(
        self, tool_name: str, retried: bool = False, file_changes_count: int = 0
    ) -> None:
        """Record step execution metrics."""
        with self._lock:
            self._total_steps_executed += 1
            if retried:
                self._total_steps_retried += 1
            self._total_file_changes += file_changes_count

    def record_http_request(self, method: str, path: str, status_code: int) -> None:
        """Record HTTP API request metrics."""
        key = f"{method} {path} ({status_code})"
        with self._lock:
            self._http_request_counters[key] += 1
            self._http_request_counters[f"status_{status_code}"] += 1
            self._http_request_counters["total"] += 1

    def record_failure(self, failure_type: str, message: str = "") -> None:
        """Record system or job failure metrics with diagnostics."""
        with self._lock:
            self._failure_counters[failure_type] += 1
            self._failure_counters["total"] += 1
            logger.warning(
                f"Failure recorded: {failure_type}",
                extra={
                    "event": "metric_failure",
                    "failure_type": failure_type,
                    "error_message": message,
                },
            )

    def record_duration(self, metric_name: str, duration_seconds: float) -> None:
        """Record a duration metric in seconds."""
        with self._lock:
            self._durations[metric_name].append(duration_seconds)
            logger.debug(
                "Duration metric recorded",
                extra={
                    "event": "metric_duration",
                    "metric_name": metric_name,
                    "duration_seconds": duration_seconds,
                },
            )

    def get_metrics_summary(self) -> dict[str, Any]:
        """Return snapshot summary of all recorded metrics."""
        with self._lock:
            duration_stats: dict[str, dict[str, float]] = {}
            for name, values in self._durations.items():
                if values:
                    duration_stats[name] = {
                        "count": len(values),
                        "total_seconds": round(sum(values), 3),
                        "avg_seconds": round(sum(values) / len(values), 3),
                        "min_seconds": round(min(values), 3),
                        "max_seconds": round(max(values), 3),
                    }

            return {
                "jobs": {
                    "total": self._job_counters["total"],
                    "queued": self._job_counters["queued"],
                    "running": self._job_counters["running"],
                    "completed": self._job_counters["completed"],
                    "failed": self._job_counters["failed"],
                },
                "tools": {
                    "total_calls": sum(self._tool_counters.values()),
                    "by_tool": dict(self._tool_counters),
                    "by_outcome": dict(self._tool_outcome_counters),
                    "selection_accuracy": self._compute_selection_accuracy(),
                },
                "plans": {
                    "total_plans": self._total_plans,
                    "total_steps_generated": self._total_steps_generated,
                },
                "steps": {
                    "total_executed": self._total_steps_executed,
                    "retried": self._total_steps_retried,
                    "file_changes": self._total_file_changes,
                },
                "failures": dict(self._failure_counters),
                "http_requests": dict(self._http_request_counters),
                "durations": duration_stats,
            }

    def _compute_selection_accuracy(self) -> dict[str, Any]:
        """Derive a human-readable selection-accuracy summary from raw counters.

        Must be called while holding self._lock (only called from within
        get_metrics_summary, which already holds it).
        """
        total = self._tool_selection_counters["total"]
        first_choice = self._tool_selection_counters["first_choice_accepted"]
        fallback = self._tool_selection_counters["fallback_used"]
        accuracy_pct = round((first_choice / total) * 100, 1) if total else None
        return {
            "total_selections": total,
            "first_choice_accepted": first_choice,
            "fallback_used": fallback,
            "first_choice_accuracy_pct": accuracy_pct,
        }

    def reset(self) -> None:
        """Reset all metrics to initial state."""
        with self._lock:
            self._job_counters.clear()
            self._tool_counters.clear()
            self._tool_outcome_counters.clear()
            self._tool_selection_counters.clear()
            self._http_request_counters.clear()
            self._failure_counters.clear()
            self._durations.clear()
            self._total_plans = 0
            self._total_steps_generated = 0
            self._total_steps_executed = 0
            self._total_steps_retried = 0
            self._total_file_changes = 0


# Global metrics collector instance
metrics_collector = MetricsCollector()

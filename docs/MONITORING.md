# RepoMind Production Monitoring & Observability Guide

This guide describes the logging, metrics, failure diagnostic, and performance tracking infrastructure of the RepoMind AI Agent system.

---

## Architecture Overview

RepoMind provides production-grade observability across all components:

```
                  ┌────────────────────────┐
                  │   FastAPI Web API      │
                  │  (Requests & Routing)  │
                  └───────────┬────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
   ┌───────────────────────┐     ┌───────────────────────┐
   │  JSON Structured Log  │     │   Metrics Collector   │
   │      Formatter        │     │  (utils/metrics.py)   │
   └───────────┬───────────┘     └───────────┬───────────┘
               │                             │
               ▼                             ▼
   ┌───────────────────────┐     ┌───────────────────────┐
   │  sys.stdout (JSON)    │     │   GET /metrics API    │
   │  CloudWatch / ELK     │     │ Prometheus / Datadog  │
   └───────────────────────┘     └───────────────────────┘
```

---

## 1. Structured JSON Logging

RepoMind uses a custom `JSONFormatter` in `utils/logging.py` that formats every log record into single-line JSON with ISO-8601 timestamps and key-value metadata.

### Standard Log Schema

```json
{
  "timestamp": "2026-08-01T17:52:00.123456+00:00",
  "level": "INFO",
  "logger": "agent.executor",
  "module": "executor",
  "function": "execute",
  "line": 332,
  "message": "Step 1 completed successfully",
  "extra": {
    "event": "step_completed",
    "step_id": 1,
    "tool_name": "code_editor",
    "duration_ms": 1245.5,
    "file_changes_count": 2
  }
}
```

### Key Log Events

| Event Name | Log Level | Emitted By | Description | Key Extra Fields |
|---|---|---|---|---|
| `job_created` | `INFO` | `job_manager` | A new agent job was queued | `job_id`, `repo_url`, `instruction` |
| `job_status_change` | `INFO` | `job_manager` | Job transitioned state | `job_id`, `old_status`, `new_status`, `elapsed_time` |
| `planner_start` | `INFO` | `agent.planner` | Plan generation started | `instruction_len`, `has_project_map` |
| `planner_complete` | `INFO` | `agent.planner` | Plan generated | `step_count`, `duration_ms`, `steps` |
| `executor_start` | `INFO` | `agent.executor` | Step execution started | `total_steps` |
| `tool_selected` | `INFO` | `agent.executor` | LLM selected a tool | `step_id`, `tool_name`, `step_task` |
| `step_retry` | `WARNING` | `agent.executor` | Step produced empty output; retrying | `step_id`, `tool_name` |
| `step_completed` | `INFO` | `agent.executor` | Step finished | `step_id`, `tool_name`, `duration_ms`, `file_changes_count` |
| `chain_complete` | `INFO` | `agent.chain` | Full turn completed | `session_id`, `planned_steps`, `executed_steps`, `duration_ms` |
| `error_invalid_repo_url` | `WARNING` | `api.errors` | 400 Bad URL error | `url`, `path` |
| `unhandled_exception` | `ERROR` | `api.errors` | 500 Unhandled error | `path`, `method`, `exception_type`, `traceback` |

---

## 2. Execution Metrics API (`GET /metrics`)

The endpoint `GET /metrics` returns a live snapshot of system metrics.

### Example Response (`GET /metrics`)

```json
{
  "jobs": {
    "total": 12,
    "queued": 0,
    "running": 1,
    "completed": 10,
    "failed": 1
  },
  "tools": {
    "total_calls": 25,
    "by_tool": {
      "code_editor": 25
    },
    "by_outcome": {
      "success": 23,
      "retry_success": 2
    }
  },
  "plans": {
    "total_plans": 10,
    "total_steps_generated": 28
  },
  "steps": {
    "total_executed": 28,
    "retried": 2,
    "file_changes": 35
  },
  "failures": {
    "InvalidRepoURLError": 1
  },
  "http_requests": {
    "total": 45,
    "status_200": 42,
    "status_400": 3
  },
  "durations": {
    "planner_duration_seconds": {
      "count": 10,
      "total_seconds": 15.42,
      "avg_seconds": 1.542,
      "min_seconds": 0.85,
      "max_seconds": 3.10
    },
    "step_execution_duration_seconds": {
      "count": 28,
      "total_seconds": 68.30,
      "avg_seconds": 2.439,
      "min_seconds": 1.10,
      "max_seconds": 5.80
    },
    "chain_duration_seconds": {
      "count": 10,
      "total_seconds": 83.72,
      "avg_seconds": 8.372,
      "min_seconds": 4.50,
      "max_seconds": 14.20
    }
  }
}
```

---

## 3. Key Performance Indicators (KPIs) & Recommended Alerts

1. **Job Failure Rate**:
   - Alert threshold: `jobs.failed / jobs.total > 0.05` (5% failure rate over 15 minutes).
2. **Step Retry Rate**:
   - Alert threshold: `steps.retried / steps.total_executed > 0.15` (High empty output retry rate).
3. **Planner Duration SLA**:
   - Alert threshold: `durations.planner_duration_seconds.avg_seconds > 10.0s`.
4. **HTTP 500 Error Rate**:
   - Alert threshold: `http_requests.status_500 > 0`.

---

## 4. Production Integration Setup

### Datadog Log Ingestion
Configure Datadog agent to tail container stdout and select JSON log parser:
```yaml
logs:
  - type: docker
    container_name: repomind-api
    service: repomind
    source: python
```

### Prometheus Scraper Setup
Scrape `/metrics` endpoint every 15 seconds in `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'repomind'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['repomind-api.internal:8000']
```

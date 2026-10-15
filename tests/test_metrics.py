from fastapi.testclient import TestClient

from api.main import app
from utils.metrics import MetricsCollector, metrics_collector


def test_metrics_collector_records_counters():
    collector = MetricsCollector()
    collector.record_job_created()
    collector.record_job_status_change("queued", "running")
    collector.record_job_status_change("running", "completed")

    collector.record_plan_generated(step_count=3)
    collector.record_tool_execution("code_editor", outcome="success")
    collector.record_step_executed("code_editor", retried=False, file_changes_count=2)
    collector.record_duration("test_duration", 1.5)

    summary = collector.get_metrics_summary()

    assert summary["jobs"]["total"] == 1
    assert summary["jobs"]["completed"] == 1
    assert summary["plans"]["total_plans"] == 1
    assert summary["plans"]["total_steps_generated"] == 3
    assert summary["tools"]["by_tool"]["code_editor"] == 1
    assert summary["steps"]["total_executed"] == 1
    assert summary["steps"]["file_changes"] == 2
    assert summary["durations"]["test_duration"]["count"] == 1
    assert summary["durations"]["test_duration"]["avg_seconds"] == 1.5


def test_metrics_api_endpoint():
    metrics_collector.reset()
    metrics_collector.record_job_created()

    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert "tools" in data
    assert "plans" in data
    assert "steps" in data
    assert "durations" in data
    assert data["jobs"]["total"] >= 1


def test_duration_metrics_recording():
    metrics_collector.reset()
    metrics_collector.record_duration("planner_duration_seconds", 0.45)
    metrics_collector.record_duration("step_execution_duration_seconds", 1.20)
    metrics_collector.record_duration("chain_duration_seconds", 1.65)

    summary = metrics_collector.get_metrics_summary()
    assert "planner_duration_seconds" in summary["durations"]
    assert summary["durations"]["planner_duration_seconds"]["avg_seconds"] == 0.45
    assert "step_execution_duration_seconds" in summary["durations"]
    assert summary["durations"]["step_execution_duration_seconds"]["avg_seconds"] == 1.20
    assert "chain_duration_seconds" in summary["durations"]
    assert summary["durations"]["chain_duration_seconds"]["avg_seconds"] == 1.65

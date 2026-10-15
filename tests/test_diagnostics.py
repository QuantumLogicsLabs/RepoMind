import io
import json

from fastapi.testclient import TestClient

from api.main import app
from utils.logging import setup_logging
from utils.metrics import metrics_collector


def test_invalid_repo_url_failure_diagnostics():
    metrics_collector.reset()
    log_buf = io.StringIO()
    setup_logging(log_level="INFO", json_format=True, stream=log_buf)

    client = TestClient(app)
    response = client.post(
        "/run", json={"repo_url": "https://invalid-url.com/repo", "instruction": "Fix bug"}
    )

    assert response.status_code == 400
    data = response.json()
    assert data["type"] == "InvalidRepoURLError"

    # Check metrics
    summary = metrics_collector.get_metrics_summary()
    assert summary["failures"]["InvalidRepoURLError"] == 1

    # Check log diagnostic output
    log_lines = log_buf.getvalue().strip().splitlines()
    error_logs = [
        json.loads(line)
        for line in log_lines
        if "InvalidRepoURLError" in line or "error_invalid_repo_url" in line
    ]
    assert len(error_logs) > 0
    assert error_logs[0]["extra"]["url"] == "https://invalid-url.com/repo"


def test_invalid_instruction_failure_diagnostics():
    metrics_collector.reset()
    client = TestClient(app)
    response = client.post(
        "/run", json={"repo_url": "https://github.com/user/repo", "instruction": "   "}
    )

    assert response.status_code == 400
    data = response.json()
    assert data["type"] == "InvalidInstructionError"

    summary = metrics_collector.get_metrics_summary()
    assert summary["failures"]["InvalidInstructionError"] == 1


def test_job_not_found_failure_diagnostics():
    metrics_collector.reset()
    client = TestClient(app)
    response = client.get("/status/non-existent-job-id")

    assert response.status_code == 404
    data = response.json()
    assert data["type"] == "JobNotFoundError"

    summary = metrics_collector.get_metrics_summary()
    assert summary["failures"]["JobNotFoundError"] == 1

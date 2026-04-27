import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from pydantic import ValidationError

from api.main import app
from api.schemas import RunRequest, JobStatus
from utils.job_manager import job_manager

# This TestClient uses httpx under the hood to fake web requests!
client = TestClient(app)

def test_pydantic_models():
    """Test Ali's Pydantic schemas validation."""
    
    # 1. Valid RunRequest
    req = RunRequest(repo_url="https://github.com/QuantumLogicsLabs/RepoMind", instruction="Fix bugs")
    assert req.branch_name == "repomind/auto-fix"  # Tests the default value

    # 2. Invalid RunRequest (missing instruction field)
    with pytest.raises(ValidationError):
        RunRequest(repo_url="https://github.com/test")


def test_job_manager_lifecycle():
    """Test Adeena's JobManager CRUD operations."""
    # 1. Create
    job_id = job_manager.create_job("https://github.com/test/repo", "test instruction")
    assert isinstance(job_id, str)

    # 2. Fetch
    job = job_manager.get(job_id)
    assert job.repo_url == "https://github.com/test/repo"
    assert job.status == JobStatus.queued

    # 3. Update
    job_manager.update(job_id, status=JobStatus.running, pr_url="https://github.com/fake/pull/1")
    updated_job = job_manager.get(job_id)
    assert updated_job.status == JobStatus.running
    assert updated_job.pr_url == "https://github.com/fake/pull/1"

    # 4. Not Found Exception
    with pytest.raises(Exception):
        job_manager.get("this_job_does_not_exist")


@patch("api.routes.run_test_executor")
def test_api_endpoints_integration(mock_executor):
    """Test the 3 API endpoints (/run, /status, /refine)."""
    # Mock the heavy agent execution so the test runs instantly
    mock_executor.return_value = {"pr_url": "https://github.com/fake/pull/2", "summary": "Done"}

    # 1. Test POST /run
    run_payload = {
        "repo_url": "https://github.com/QuantumLogicsLabs/RepoMind",
        "instruction": "Test run"
    }
    run_resp = client.post("/run", json=run_payload)
    assert run_resp.status_code == 200
    
    job_id = run_resp.json()["job_id"]
    assert run_resp.json()["status"] == "queued"

    # 2. Test GET /status
    status_resp = client.get(f"/status/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] in ["queued", "running", "completed"]

    # 3. Test POST /refine
    refine_payload = {
        "job_id": job_id,
        "instruction": "Make it better"
    }
    refine_resp = client.post("/refine", json=refine_payload)
    assert refine_resp.status_code == 200
    assert refine_resp.json()["job_id"] == job_id


def test_api_error_handling():
    """
    Test what happens when users send bad data.
    NOTE: This test is EXPECTED to fail because of a bug in main.py!
    """
    # Test Invalid GitHub URL (Should return 400 Bad Request)
    bad_url_resp = client.post("/run", json={"repo_url": "https://gitlab.com/test", "instruction": "test"})
    assert bad_url_resp.status_code == 400

    # Test Job Not Found (Should return 404 Not Found)
    bad_status_resp = client.get("/status/fake_12345")
    assert bad_status_resp.status_code == 404
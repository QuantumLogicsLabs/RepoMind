from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.errors import JobNotFoundError
from api.main import app
from api.schemas import JobStatus, RunRequest
 task-10-persistent-jobs

from config.settings import get_settings
from tools.agent_runner import validate_credentials
from tools.github_tool import _redact_secret
 main
from utils.job_manager import job_manager

# This TestClient uses httpx under the hood to fake web requests!
client = TestClient(app)


def test_pydantic_models():
    """Test Ali's Pydantic schemas validation."""

    # 1. Valid RunRequest
    req = RunRequest(
        repo_url="https://github.com/QuantumLogicsLabs/RepoMind", instruction="Fix bugs"
    )
    assert req.branch_name == "repomind/auto-fix"  # Tests the default value

    # 2. Invalid RunRequest (missing instruction field)
    with pytest.raises(ValidationError):
        RunRequest(repo_url="https://github.com/test")


def test_settings_are_initialized_with_environment_groq_key(monkeypatch):
    """Settings should be constructible when a Groq key is provided through the environment."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    settings = get_settings()
    assert settings.groq_api_key == "test-key"


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
 task-10-persistent-jobs
with pytest.raises(JobNotFoundError):
    job_manager.get("this_job_does_not_exist")

    with pytest.raises(JobNotFoundError):
        job_manager.get("this_job_does_not_exist")
 main


@patch("api.routes.run_agent")
def test_api_endpoints_integration(mock_run_agent):
    mock_run_agent.return_value = {"pr_url": "https://github.com/fake/pull/2", "summary": "Done"}

    # 1. Test POST /run
    run_payload = {
        "repo_url": "https://github.com/QuantumLogicsLabs/RepoMind",
        "instruction": "Test run",
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
    refine_payload = {"job_id": job_id, "instruction": "Make it better"}
    refine_resp = client.post("/refine", json=refine_payload)
    assert refine_resp.status_code == 200
    assert refine_resp.json()["job_id"] == job_id


def test_api_error_handling():
    """
    Test what happens when users send bad data.
    """
    # Test Invalid GitHub URL (Should return 400 Bad Request)
    bad_url_resp = client.post(
        "/run", json={"repo_url": "https://gitlab.com/test", "instruction": "test"}
    )
    assert bad_url_resp.status_code == 400

    # Test Job Not Found (Should return 404 Not Found)
    bad_status_resp = client.get("/status/fake_12345")
    assert bad_status_resp.status_code == 404


def test_run_request_masks_credentials():
    """Credentials in RunRequest must never appear in str()/repr() output."""
    req = RunRequest(
        repo_url="https://github.com/QuantumLogicsLabs/RepoMind",
        instruction="Fix bugs",
        github_pat="ghp_supersecrettoken123",
        llm_provider="groq",
        llm_api_key="gsk_supersecretkey456",
    )

    rendered = str(req)
    assert "ghp_supersecrettoken123" not in rendered
    assert "gsk_supersecretkey456" not in rendered
    # The real value must still be retrievable when explicitly requested
    assert req.github_pat.get_secret_value() == "ghp_supersecrettoken123"
    assert req.llm_api_key.get_secret_value() == "gsk_supersecretkey456"


def test_run_request_credentials_are_optional():
    """Existing callers that don't supply credentials must still work."""
    req = RunRequest(
        repo_url="https://github.com/QuantumLogicsLabs/RepoMind",
        instruction="Fix bugs",
    )
    assert req.github_pat is None
    assert req.llm_api_key is None
    assert req.llm_provider is None


def test_resolve_github_token_prefers_request_scoped_value():
    """A request-scoped token must override the server default."""
    from pydantic import SecretStr

    settings = get_settings()
    request_token = SecretStr("ghp_request_scoped_token")

    resolved = settings.resolve_github_token(request_token)
    assert resolved == "ghp_request_scoped_token"


def test_resolve_llm_credentials_prefers_request_scoped_value():
    """A request-scoped LLM key/provider must override the server default."""
    from pydantic import SecretStr

    settings = get_settings()
    provider, key = settings.resolve_llm_credentials("groq", SecretStr("gsk_request_key"))

    assert provider == "groq"
    assert key == "gsk_request_key"


def test_resolve_llm_credentials_rejects_unsupported_provider():
    """An unrecognised provider name must raise, not silently fall through."""
    from pydantic import SecretStr

    settings = get_settings()
    with pytest.raises(ValueError):
        settings.resolve_llm_credentials("not_a_real_provider", SecretStr("some_key"))


def test_redact_secret_removes_token_from_text():
    """_redact_secret must replace every occurrence of the secret, and be a no-op for empty secrets."""
    text = "Cloning https://ghp_abc123@github.com/foo/bar.git failed"
    redacted = _redact_secret(text, "ghp_abc123")

    assert "ghp_abc123" not in redacted
    assert "***REDACTED***" in redacted
    # No secret supplied → text passes through unchanged
    assert _redact_secret(text, None) == text
    assert _redact_secret(text, "") == text


@patch("tools.agent_runner.requests.get")
def test_validate_credentials_rejects_invalid_github_token(mock_get):
    """validate_credentials must raise a clear ValueError on a 401 from GitHub, without a real API call."""
    mock_get.return_value.status_code = 401

    with pytest.raises(ValueError, match="GitHub token is invalid or expired"):
        validate_credentials(
            github_token="not_a_real_token",
            llm_provider="groq",
            llm_api_key="not_a_real_key",
        )


@patch("tools.agent_runner.ChatGroq")
@patch("tools.agent_runner.requests.get")
def test_validate_credentials_passes_with_valid_mocked_credentials(mock_get, mock_chat_groq):
    """validate_credentials must not raise when both GitHub and LLM checks succeed."""
    mock_get.return_value.status_code = 200
    mock_chat_groq.return_value.invoke.return_value = "pong"

    # Should not raise
    validate_credentials(
        github_token="fake_but_valid_looking_token",
        llm_provider="groq",
        llm_api_key="fake_but_valid_looking_key",
    )

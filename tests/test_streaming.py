from fastapi.testclient import TestClient

from api.main import app
from utils.job_manager import job_manager

client = TestClient(app)


def test_job_manager_event_bus():
    job_id = job_manager.create_job(
        repo_url="https://github.com/octocat/Hello-World",
        instruction="Fix bug in main",
    )
    job = job_manager.get(job_id)
    assert len(job.events) == 1
    assert job.events[0]["stage"] == "queued"

    # Add execution events
    job_manager.add_event(job_id, stage="cloning", message="Cloning repo", progress=10.0)
    job_manager.add_event(job_id, stage="parsing", message="Parsing files", progress=25.0)

    record = job_manager.get(job_id)
    assert len(record.events) == 3
    assert record.current_stage == "parsing"
    assert record.progress == 25.0


def test_job_manager_reconnect_catchup():
    job_id = job_manager.create_job(
        repo_url="https://github.com/octocat/Hello-World",
        instruction="Add feature",
    )
    job_manager.add_event(job_id, stage="cloning", message="Step 1", progress=10.0)
    job_manager.add_event(job_id, stage="parsing", message="Step 2", progress=25.0)
    job_manager.add_event(job_id, stage="planning", message="Step 3", progress=40.0)

    # Reconnect with last_event_id=2 -> should receive events after ID 2 (ID 3 and 4)
    queue, missed = job_manager.subscribe(job_id, last_event_id=2)
    assert len(missed) == 2
    assert missed[0]["id"] == 3
    assert missed[1]["id"] == 4
    job_manager.unsubscribe(job_id, queue)


def test_sse_streaming_endpoint():
    job_id = job_manager.create_job(
        repo_url="https://github.com/octocat/Hello-World",
        instruction="Refactor code",
    )
    job_manager.add_event(job_id, stage="cloning", message="Cloning repository...", progress=10.0)
    job_manager.add_event(job_id, stage="completed", message="Done!", progress=100.0)
    job_manager.update(job_id, status="completed")

    response = client.get(f"/stream/{job_id}")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    content = response.text
    assert "event: progress" in content
    assert "cloning" in content
    assert "completed" in content


def test_sse_reconnect_last_event_id_param():
    job_id = job_manager.create_job(
        repo_url="https://github.com/octocat/Hello-World",
        instruction="Refactor code",
    )
    job_manager.add_event(job_id, stage="cloning", message="Step 1", progress=10.0)
    job_manager.add_event(job_id, stage="parsing", message="Step 2", progress=25.0)
    job_manager.add_event(job_id, stage="completed", message="Done!", progress=100.0)
    job_manager.update(job_id, status="completed")

    response = client.get(f"/stream/{job_id}?last_event_id=2")
    assert response.status_code == 200
    content = response.text
    # Event ID 1 (queued) and 2 (cloning) should be skipped
    assert "id: 3" in content or "id: 4" in content

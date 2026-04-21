from core.job_manager import job_manager

# In POST /run route:
job_id = job_manager.create_job(repo_url, instruction)   # → UUID string

# In agent/executor.py when work starts:
job_manager.set_running(job_id)

# In tools/pr_tool.py after PR is opened:
job_manager.complete(job_id, pr_url="https://...", diff_summary="6 files changed")

# In any try/except when something breaks:
job_manager.fail(job_id, reason=str(exc))

# In GET /status route:
record = job_manager.get(job_id)   # returns JobRecord or raises JobNotFoundError

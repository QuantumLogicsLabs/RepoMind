from fastapi import Request
from fastapi.responses import JSONResponse


class InvalidRepoURLError(Exception):
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"Invalid repository URL: {url}")


class InvalidInstructionError(Exception):
    def __init__(self):
        super().__init__("Instruction cannot be empty.")


class JobAlreadyRunningError(Exception):
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job '{job_id}' is already running.")


class JobNotFoundError(Exception):
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job '{job_id}' not found.")


class AgentTimeoutError(Exception):
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job '{job_id}' timed out after 120 seconds without completing.")


async def invalid_repo_url_handler(request: Request, exc: InvalidRepoURLError):
    return JSONResponse(
        status_code=400,
        content={"status": "error", "code": 400, "type": "InvalidRepoURLError",
                 "message": f"Invalid repository URL: {exc.url}. URL must start with https://github.com/"},
    )


async def invalid_instruction_handler(request: Request, exc: InvalidInstructionError):
    return JSONResponse(
        status_code=400,
        content={"status": "error", "code": 400, "type": "InvalidInstructionError",
                 "message": "Instruction cannot be empty. Please provide a valid instruction."},
    )


async def job_already_running_handler(request: Request, exc: JobAlreadyRunningError):
    return JSONResponse(
        status_code=409,
        content={"status": "error", "code": 409, "type": "JobAlreadyRunningError",
                 "message": f"Job '{exc.job_id}' is already running. Wait for it to finish before refining."},
    )


async def job_not_found_handler(request: Request, exc: JobNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"status": "error", "code": 404, "type": "JobNotFoundError",
                 "message": f"Job '{exc.job_id}' was not found."},
    )


async def agent_timeout_handler(request: Request, exc: AgentTimeoutError):
    return JSONResponse(
        status_code=408,
        content={"status": "error", "code": 408, "type": "AgentTimeoutError",
                 "message": f"Job '{exc.job_id}' timed out after 120 seconds without completing."},
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "code": 500, "type": "InternalServerError",
                 "message": "An unexpected error occurred. Please try again or contact support."},
    )


def register_error_handlers(app) -> None:
    app.add_exception_handler(InvalidRepoURLError, invalid_repo_url_handler)
    app.add_exception_handler(InvalidInstructionError, invalid_instruction_handler)
    app.add_exception_handler(JobAlreadyRunningError, job_already_running_handler)
    app.add_exception_handler(JobNotFoundError, job_not_found_handler)
    app.add_exception_handler(AgentTimeoutError, agent_timeout_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

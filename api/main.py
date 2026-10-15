import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.errors import register_error_handlers
from api.routes import router
from config.settings import get_settings
from utils.logging import get_logger, setup_logging
from utils.metrics import metrics_collector

logger = get_logger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(log_level=settings.log_level)
    logger.info(
        "RepoMind API starting up",
        extra={"app_env": settings.app_env, "model": settings.active_llm_model},
    )
    yield
    logger.info("RepoMind API shutting down")


# ── App Initialization ────────────────────────────────────────────────────────

app = FastAPI(
    title="RepoMind API",
    description=(
        "The ML core of HackingTheRepo. "
        "Receives a natural-language instruction and a repo URL, "
        "clones the repo, plans and applies code changes, and opens a Pull Request automatically."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Allows the HackingTheRepo web platform to call this service from the browser

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock this down to the platform domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_sec = time.perf_counter() - start_time
    duration_ms = round(duration_sec * 1000, 2)

    metrics_collector.record_http_request(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
    )
    metrics_collector.record_duration("http_request_duration", duration_sec)

    logger.info(
        "HTTP request processed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else None,
        },
    )
    return response


# ── Global Error Handler ──────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception in request handler",
        exc_info=exc,
        extra={"method": request.method, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={"status": "failed", "message": str(exc)},
    )


# ── Routers ───────────────────────────────────────────────────────────────────
register_error_handlers(app)
app.include_router(router)

# ── Health Endpoints ──────────────────────────────────────────────────────────


@app.get("/", tags=["Health"])
async def root():
    return {"service": "RepoMind", "status": "running"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}

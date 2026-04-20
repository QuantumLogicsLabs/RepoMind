from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from api.routes import router

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
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Allows the HackingTheRepo web platform to call this service from the browser

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Lock this down to the platform domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global Error Handler ──────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "failed", "message": str(exc)},
    )

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(router)

# ── Health Endpoints ──────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
async def root():
    return {"service": "RepoMind", "status": "running"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}

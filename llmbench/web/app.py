"""FastAPI application for LLMBench web service."""
import logging
import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from .database import init_db

logger = logging.getLogger("llmbench.timing")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [TIMING] %(message)s", "%H:%M:%S"))
    logger.addHandler(h)

# Create FastAPI app
app = FastAPI(
    title="LLMBench Web",
    version="1.0.0",
    description="LLM Inference Server Benchmark Web Service",
)


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    """Log endpoint duration; flag slow API requests."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    # Skip noisy paths
    if path.startswith("/static") or path == "/health" or path.startswith("/.well-known"):
        return response
    marker = "🐌" if duration_ms > 1000 else ("⚠️ " if duration_ms > 300 else "✓ ")
    logger.info(f"{marker} {request.method} {path} → {response.status_code}  {duration_ms:7.1f}ms")
    return response

# Get base directory
BASE_DIR = Path(__file__).parent

# Mount static files
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Configure Jinja2 templates
templates_dir = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@app.on_event("startup")
async def startup_event():
    """Initialize database and pre-warm slow caches."""
    await init_db()
    print("✅ Database initialized")

    # Background warming for /api/test-runs:
    # - Computes new value WITHOUT invalidating cache (user always reads cached)
    # - Atomically swaps in fresh result when ready
    # - Runs every 4 min (within 5 min TTL) so cache never expires under load
    import asyncio
    from .database import AsyncSessionLocal
    from .routes.api import _warm_test_runs_safe

    async def _warm_loop():
        await asyncio.sleep(30)  # let server settle + serve any initial requests
        while True:
            try:
                t = time.perf_counter()
                await _warm_test_runs_safe()
                print(f"✅ /api/test-runs refreshed in {(time.perf_counter()-t)*1000:.0f}ms")
            except Exception as e:
                print(f"⚠️  warming failed: {e}")
            await asyncio.sleep(240)  # 4 min, before 5 min TTL expires

    asyncio.create_task(_warm_loop())


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    print("👋 Shutting down...")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "llmbench-web"}


# Import and include routers
from .routes import api, ui

app.include_router(api.router, prefix="/api", tags=["API"])
app.include_router(ui.router, tags=["UI"])

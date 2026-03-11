"""FastAPI application for LLMBench web service."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .database import init_db

# Create FastAPI app
app = FastAPI(
    title="LLMBench Web",
    version="1.0.0",
    description="LLM Inference Server Benchmark Web Service",
)

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
    """Initialize database on startup."""
    await init_db()
    print("✅ Database initialized")


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

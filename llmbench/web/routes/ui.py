"""Web UI routes (HTML responses)."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..app import templates
from ..crud import BenchmarkCRUD

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - dashboard with client-side data loading."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


@router.get("/benchmarks", response_class=HTMLResponse)
async def list_benchmarks_ui(
    request: Request,
    status: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Benchmarks list page."""
    benchmarks = await BenchmarkCRUD.list_all(db, status=status, limit=50)
    total = await BenchmarkCRUD.count_all(db, status=status)

    return templates.TemplateResponse(
        "benchmarks_list.html",
        {
            "request": request,
            "benchmarks": benchmarks,
            "total": total,
            "current_status": status,
        },
    )


@router.get("/benchmarks/create", response_class=HTMLResponse)
async def create_benchmark_ui(request: Request):
    """Benchmark creation form page."""
    return templates.TemplateResponse(
        "benchmark_create.html",
        {
            "request": request,
        },
    )


@router.get("/benchmarks/{uuid}", response_class=HTMLResponse)
async def benchmark_detail_ui(
    uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Benchmark details page."""
    benchmark = await BenchmarkCRUD.get_with_scenarios(db, uuid)
    if not benchmark:
        # Return 404 page
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Benchmark not found", "code": 404},
            status_code=404,
        )

    return templates.TemplateResponse(
        "benchmark_detail.html",
        {
            "request": request,
            "benchmark": benchmark,
            "scenarios": benchmark.scenarios,
        },
    )


@router.get("/benchmarks/{uuid}/edit", response_class=HTMLResponse)
async def edit_benchmark_ui(
    uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Benchmark edit page."""
    benchmark = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not benchmark:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Benchmark not found", "code": 404},
            status_code=404,
        )

    return templates.TemplateResponse(
        "benchmark_edit.html",
        {
            "request": request,
            "benchmark": benchmark,
        },
    )

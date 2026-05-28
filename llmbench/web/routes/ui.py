"""Web UI routes (HTML responses)."""
from datetime import timezone, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..app import templates
from ..crud import BenchmarkCRUD, ChallengeCRUD

router = APIRouter()


def _to_taipei_string(dt, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not dt:
        return "-"
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    taipei_tz = timezone(timedelta(hours=8))
    return aware.astimezone(taipei_tz).strftime(fmt)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - dashboard with client-side data loading."""
    return templates.TemplateResponse(
        request,
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
        request,
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
        request,
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
            request,
            "error.html",
            {"request": request, "error": "Benchmark not found", "code": 404},
            status_code=404,
        )

    return templates.TemplateResponse(
        request,
        "benchmark_detail.html",
        {
            "request": request,
            "benchmark": benchmark,
            "scenarios": benchmark.scenarios,
        },
    )


@router.get("/challenges", response_class=HTMLResponse)
async def list_challenges_ui(
    request: Request,
    task_type: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Challenges list page."""
    challenges = await ChallengeCRUD.list_all(db, task_type=task_type, limit=100)
    total = await ChallengeCRUD.count_all(db, task_type=task_type)
    challenge_rows = [
        {
            "obj": c,
            "created_at_local": _to_taipei_string(c.created_at),
            "updated_at_local": _to_taipei_string(c.updated_at),
        }
        for c in challenges
    ]
    return templates.TemplateResponse(
        request,
        "challenges_list.html",
        {"request": request, "challenges": challenges, "challenge_rows": challenge_rows, "total": total, "current_task_type": task_type},
    )


@router.get("/challenges/create", response_class=HTMLResponse)
async def create_challenge_ui(request: Request):
    """Challenge creation form."""
    return templates.TemplateResponse(request, "challenge_create.html", {"request": request})


@router.get("/challenges/import/threads", response_class=HTMLResponse)
async def import_threads_ui(request: Request):
    """Threads import form."""
    return templates.TemplateResponse(request, "challenge_import_threads.html", {"request": request})


@router.get("/challenges/import/taiwan-md", response_class=HTMLResponse)
async def import_taiwan_md_ui(request: Request):
    """Taiwan.md import form."""
    return templates.TemplateResponse(request, "challenge_import_taiwan_md.html", {"request": request})


@router.get("/challenges/import/taiwan-knowledge", response_class=HTMLResponse)
async def import_taiwan_knowledge_ui(request: Request):
    """Taiwan knowledge import form."""
    return templates.TemplateResponse(request, "challenge_import_taiwan_knowledge.html", {"request": request})


@router.get("/challenges/import/ptt-movie", response_class=HTMLResponse)
async def import_ptt_movie_ui(request: Request):
    """PTT Movie import form."""
    return templates.TemplateResponse(request, "challenge_import_ptt_movie.html", {"request": request})


@router.get("/challenges/import/school-exam", response_class=HTMLResponse)
async def import_school_exam_ui(request: Request):
    """School exam import form."""
    return templates.TemplateResponse(request, "challenge_import_school_exam.html", {"request": request})


@router.get("/challenges/{uuid}", response_class=HTMLResponse)
async def challenge_detail_ui(uuid: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Challenge detail page."""
    challenge = await ChallengeCRUD.get_by_uuid(db, uuid)
    if not challenge:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"request": request, "error": "Challenge not found", "code": 404},
            status_code=404,
        )
    return templates.TemplateResponse(request, "challenge_detail.html", {"request": request, "challenge": challenge, "created_at_local": _to_taipei_string(challenge.created_at), "updated_at_local": _to_taipei_string(challenge.updated_at)})


@router.get("/challenges/{uuid}/edit", response_class=HTMLResponse)
async def edit_challenge_ui(uuid: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Challenge edit page."""
    challenge = await ChallengeCRUD.get_by_uuid(db, uuid)
    if not challenge:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"request": request, "error": "Challenge not found", "code": 404},
            status_code=404,
        )
    return templates.TemplateResponse(request, "challenge_edit.html", {"request": request, "challenge": challenge})


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
            request,
            "error.html",
            {"request": request, "error": "Benchmark not found", "code": 404},
            status_code=404,
        )

    return templates.TemplateResponse(
        request,
        "benchmark_edit.html",
        {
            "request": request,
            "benchmark": benchmark,
        },
    )

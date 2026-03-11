"""REST API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io
import json
import asyncio

from ..database import get_db
from ..crud import BenchmarkCRUD, ScenarioCRUD, ServerCRUD
from ..schemas import (
    BenchmarkCreate,
    BenchmarkResponse,
    BenchmarkListItem,
    BenchmarkStatus,
    ServerCreate,
    ServerResponse,
)
from ..models import Benchmark
from ..tasks import run_benchmark_task

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Get dashboard statistics."""
    total = await BenchmarkCRUD.count_all(db)
    running = await BenchmarkCRUD.count_all(db, status="running")
    completed = await BenchmarkCRUD.count_all(db, status="completed")
    failed = await BenchmarkCRUD.count_all(db, status="failed")
    pending = await BenchmarkCRUD.count_all(db, status="pending")

    # Get recent benchmarks
    recent = await BenchmarkCRUD.list_all(db, limit=5, offset=0)

    return {
        "total_benchmarks": total,
        "running_count": running,
        "completed_count": completed,
        "failed_count": failed,
        "pending_count": pending,
        "recent_benchmarks": [
            {
                "uuid": b.uuid,
                "name": b.name,
                "status": b.status,
                "created_at": b.created_at.isoformat(),
                "runtime_sec": b.runtime_sec,
            }
            for b in recent
        ],
    }


@router.get("/benchmarks", response_model=List[BenchmarkListItem])
async def list_benchmarks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all benchmarks with optional filtering."""
    benchmarks = await BenchmarkCRUD.list_all(db, status=status, limit=limit, offset=offset)
    return benchmarks


@router.post("/benchmarks", response_model=BenchmarkResponse)
async def create_benchmark(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    config_file: Optional[UploadFile] = File(None),
    config_text: Optional[str] = Form(None),
    auto_run: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """Create a new benchmark from YAML config and optionally start execution.

    Args:
        background_tasks: FastAPI background tasks
        name: Benchmark name
        description: Optional description
        config_file: YAML config file upload
        config_text: YAML config as text
        auto_run: If True, automatically start benchmark execution (default: True)
        db: Database session
    """
    # Get config YAML from either file or text
    if config_file:
        config_yaml = (await config_file.read()).decode("utf-8")
    elif config_text:
        config_yaml = config_text
    else:
        raise HTTPException(status_code=400, detail="Must provide config_file or config_text")

    # Validate config
    try:
        from ...config.loader import load_config_from_string
        cfg = load_config_from_string(config_yaml)
        config_fingerprint = cfg.fingerprint()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {str(e)}")

    # Extract metadata
    metadata = cfg.metadata if hasattr(cfg, "metadata") else {}
    metadata_json = json.dumps(metadata) if metadata else None

    # Create benchmark
    benchmark = await BenchmarkCRUD.create(
        session=db,
        name=name,
        description=description,
        config_yaml=config_yaml,
        config_fingerprint=config_fingerprint,
        metadata_json=metadata_json,
    )
    await db.commit()
    await db.refresh(benchmark)

    # Start benchmark execution in background if auto_run is True
    if auto_run:
        # Use asyncio.create_task instead of BackgroundTasks for better async support
        from ..task_manager import task_manager
        task = asyncio.create_task(run_benchmark_task(benchmark.uuid, config_yaml))
        task_manager.register_task(benchmark.uuid, task)

    # Return with empty scenarios list (benchmark is newly created)
    return BenchmarkResponse(
        uuid=benchmark.uuid,
        name=benchmark.name,
        description=benchmark.description,
        config_fingerprint=benchmark.config_fingerprint,
        status=benchmark.status,
        created_at=benchmark.created_at,
        started_at=benchmark.started_at,
        completed_at=benchmark.completed_at,
        runtime_sec=benchmark.runtime_sec,
        error_message=benchmark.error_message,
        scenarios=[],
    )


@router.get("/benchmarks/{uuid}", response_model=BenchmarkResponse)
async def get_benchmark(
    uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Get benchmark details with scenarios."""
    benchmark = await BenchmarkCRUD.get_with_scenarios(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Manually construct response to avoid async relationship access issues
    from ..schemas import ScenarioResponse
    scenarios = [
        ScenarioResponse(
            scenario_name=s.scenario_name,
            server_name=s.server_name,
            request_count=s.request_count,
            error_count=s.error_count,
            p50_ms=s.p50_ms,
            p95_ms=s.p95_ms,
            p99_ms=s.p99_ms,
            avg_ms=s.avg_ms,
            tokens_per_sec_output=s.tokens_per_sec_output,
            tokens_per_sec_total=s.tokens_per_sec_total,
            error_rate=s.error_rate,
        )
        for s in benchmark.scenarios
    ]

    return BenchmarkResponse(
        uuid=benchmark.uuid,
        name=benchmark.name,
        description=benchmark.description,
        config_fingerprint=benchmark.config_fingerprint,
        status=benchmark.status,
        created_at=benchmark.created_at,
        started_at=benchmark.started_at,
        completed_at=benchmark.completed_at,
        runtime_sec=benchmark.runtime_sec,
        error_message=benchmark.error_message,
        scenarios=scenarios,
    )


@router.get("/benchmarks/{uuid}/status", response_model=BenchmarkStatus)
async def get_benchmark_status(
    uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Get current benchmark status (for polling)."""
    benchmark = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Calculate progress if running
    progress = None
    current_request_count = None

    if benchmark.status == "running" and benchmark.scenarios:
        # Sum up request counts from scenarios
        current_request_count = sum(s.request_count or 0 for s in benchmark.scenarios)
        # Progress is approximate (we don't know total expected requests easily)
        progress = min(int((current_request_count / 100) * 100), 100) if current_request_count else 0

    return BenchmarkStatus(
        uuid=benchmark.uuid,
        status=benchmark.status,
        progress=progress,
        current_request_count=current_request_count,
    )


@router.post("/benchmarks/{uuid}/run")
async def run_benchmark_endpoint(
    uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Manually start a benchmark that was created with auto_run=False."""
    benchmark = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if benchmark.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Can only run pending benchmarks (current status: {benchmark.status})"
        )

    # Start benchmark execution in background
    from ..task_manager import task_manager
    task = asyncio.create_task(run_benchmark_task(benchmark.uuid, benchmark.config_yaml))
    task_manager.register_task(benchmark.uuid, task)

    return JSONResponse({"message": "Benchmark started", "uuid": uuid})


@router.post("/benchmarks/{uuid}/cancel")
async def cancel_benchmark(
    uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running benchmark."""
    from ..task_manager import task_manager
    from ..log_handler import add_log

    benchmark = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if benchmark.status not in ["pending", "running"]:
        raise HTTPException(status_code=400, detail="Can only cancel pending or running benchmarks")

    # Request task cancellation
    cancelled = task_manager.cancel_task(uuid)

    # Log the cancellation request
    await add_log(db, benchmark.id, "WARNING", "Cancellation requested by user", "system")

    # Update status to cancelled
    await BenchmarkCRUD.update_status(db, uuid, status="cancelled")
    await db.commit()

    return {
        "message": "Benchmark cancellation requested" if cancelled else "Benchmark marked as cancelled",
        "uuid": uuid,
        "task_found": cancelled
    }


@router.delete("/benchmarks/{uuid}")
async def delete_benchmark(
    uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a benchmark and all related data."""
    benchmark = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    await BenchmarkCRUD.delete(db, uuid)

    return {"message": "Benchmark deleted", "uuid": uuid}


@router.post("/benchmarks/{uuid}/rerun")
async def rerun_benchmark(
    uuid: str,
    auto_run: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """Create a new benchmark run with the same configuration."""
    from ..tasks import run_benchmark_task

    # Get the original benchmark
    original = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not original:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Get the next run number
    next_run_number = await BenchmarkCRUD.get_next_run_number(db, uuid)

    # Determine the root parent
    root_parent_uuid = original.parent_uuid if original.parent_uuid else uuid

    # Create new benchmark with same config
    new_benchmark = await BenchmarkCRUD.create(
        session=db,
        name=f"{original.name} (Run #{next_run_number})",
        description=original.description,
        config_yaml=original.config_yaml,
        config_fingerprint=original.config_fingerprint,
        parent_uuid=root_parent_uuid,
        run_number=next_run_number,
    )
    await db.commit()

    # Start execution if auto_run is True
    if auto_run:
        from ..task_manager import task_manager
        task = asyncio.create_task(run_benchmark_task(new_benchmark.uuid, new_benchmark.config_yaml))
        task_manager.register_task(new_benchmark.uuid, task)

    return BenchmarkResponse(
        uuid=new_benchmark.uuid,
        name=new_benchmark.name,
        description=new_benchmark.description,
        status=new_benchmark.status,
        config_fingerprint=new_benchmark.config_fingerprint,
        created_at=new_benchmark.created_at,
        started_at=new_benchmark.started_at,
        completed_at=new_benchmark.completed_at,
        runtime_sec=new_benchmark.runtime_sec,
        error_message=new_benchmark.error_message,
        scenarios=[],
    )


@router.get("/benchmarks/{uuid}/history")
async def get_benchmark_history(
    uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all benchmarks in the same history chain."""
    history = await BenchmarkCRUD.get_history(db, uuid)

    from ..schemas import BenchmarkListItem
    return [
        BenchmarkListItem(
            uuid=b.uuid,
            name=b.name,
            description=b.description,
            status=b.status,
            created_at=b.created_at,
            runtime_sec=b.runtime_sec,
            error_message=b.error_message,
        )
        for b in history
    ]


@router.get("/benchmarks/{uuid}/config")
async def get_benchmark_config(
    uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the YAML configuration of a benchmark for editing."""
    benchmark = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    return {
        "uuid": benchmark.uuid,
        "name": benchmark.name,
        "description": benchmark.description,
        "config_yaml": benchmark.config_yaml,
        "config_fingerprint": benchmark.config_fingerprint,
    }


@router.get("/benchmarks/{uuid}/logs")
async def get_benchmark_logs(
    uuid: str,
    since_id: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Get execution logs for a benchmark.

    Args:
        uuid: Benchmark UUID
        since_id: Only return logs with ID > since_id (for polling)
        limit: Maximum number of logs to return
    """
    from sqlalchemy import select
    from ..models import BenchmarkLog

    # Get benchmark
    benchmark = await BenchmarkCRUD.get_by_uuid(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Query logs
    query = (
        select(BenchmarkLog)
        .where(BenchmarkLog.benchmark_id == benchmark.id)
        .where(BenchmarkLog.id > since_id)
        .order_by(BenchmarkLog.id.asc())
        .limit(limit)
    )

    result = await db.execute(query)
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "level": log.level,
            "message": log.message,
            "source": log.source,
        }
        for log in logs
    ]


@router.get("/benchmarks/{uuid}/export")
async def export_benchmark(
    uuid: str,
    format: str = Query("json", regex="^(json|csv|markdown)$"),
    db: AsyncSession = Depends(get_db),
):
    """Export benchmark results."""
    benchmark = await BenchmarkCRUD.get_with_scenarios(db, uuid)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if format == "json":
        # Return full benchmark data as JSON
        data = {
            "benchmark": benchmark.to_dict(),
            "scenarios": [s.to_dict() for s in benchmark.scenarios],
        }
        return JSONResponse(content=data)

    elif format == "csv":
        # Generate CSV of scenario metrics
        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["scenario_name", "server_name", "request_count", "p50_ms", "p95_ms", "tokens_per_sec_output", "error_rate"],
        )
        writer.writeheader()

        for scenario in benchmark.scenarios:
            writer.writerow({
                "scenario_name": scenario.scenario_name,
                "server_name": scenario.server_name,
                "request_count": scenario.request_count or 0,
                "p50_ms": scenario.p50_ms or 0,
                "p95_ms": scenario.p95_ms or 0,
                "tokens_per_sec_output": scenario.tokens_per_sec_output or 0,
                "error_rate": scenario.error_rate or 0,
            })

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=benchmark_{uuid}.csv"},
        )

    elif format == "markdown":
        # Generate markdown report (simple version)
        lines = [
            f"# Benchmark: {benchmark.name}",
            "",
            f"**Status**: {benchmark.status}",
            f"**Created**: {benchmark.created_at}",
            f"**Runtime**: {benchmark.runtime_sec:.2f}s" if benchmark.runtime_sec else "**Runtime**: N/A",
            "",
            "## Scenarios",
            "",
        ]

        for scenario in benchmark.scenarios:
            lines.extend([
                f"### {scenario.scenario_name} - {scenario.server_name}",
                "",
                f"- Requests: {scenario.request_count or 0}",
                f"- p50: {scenario.p50_ms:.1f}ms" if scenario.p50_ms else "- p50: N/A",
                f"- p95: {scenario.p95_ms:.1f}ms" if scenario.p95_ms else "- p95: N/A",
                f"- Throughput: {scenario.tokens_per_sec_output:.2f} tokens/s" if scenario.tokens_per_sec_output else "- Throughput: N/A",
                f"- Error Rate: {scenario.error_rate:.3f}" if scenario.error_rate is not None else "- Error Rate: N/A",
                "",
            ])

        content = "\n".join(lines)
        return StreamingResponse(
            iter([content]),
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=benchmark_{uuid}.md"},
        )


@router.post("/validate-config")
async def validate_config(
    config_text: str = Form(...),
):
    """Validate a YAML config without creating a benchmark."""
    try:
        from ...config.loader import load_config_from_string
        cfg = load_config_from_string(config_text)
        return {
            "valid": True,
            "fingerprint": cfg.fingerprint(),
            "servers": [s.name for s in cfg.servers],
            "scenarios": [s.name for s in cfg.scenarios],
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }


# Server management endpoints
@router.get("/servers", response_model=List[ServerResponse])
async def list_servers(db: AsyncSession = Depends(get_db)):
    """List all saved server configurations."""
    servers = await ServerCRUD.list_all(db)
    return servers


@router.post("/servers", response_model=ServerResponse)
async def create_server(
    server: ServerCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new server configuration."""
    # Check if server with same name exists
    existing = await ServerCRUD.get_by_name(db, server.name)
    if existing:
        raise HTTPException(status_code=400, detail="Server with this name already exists")

    new_server = await ServerCRUD.create(
        session=db,
        name=server.name,
        type=server.type,
        base_url=server.base_url,
        model=server.model,
        config_json=server.config_json,
    )
    return new_server


@router.delete("/servers/{name}")
async def delete_server(
    name: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a server configuration."""
    server = await ServerCRUD.get_by_name(db, name)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    await ServerCRUD.delete(db, name)
    return {"message": "Server deleted", "name": name}

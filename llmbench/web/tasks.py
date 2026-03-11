"""Background task runner for executing benchmarks.

This module handles async execution of benchmarks and stores results to database.
"""
from __future__ import annotations
import asyncio
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .database import AsyncSessionLocal
from .crud import BenchmarkCRUD, ScenarioCRUD
from .log_handler import add_log
from .task_manager import task_manager
from ..config.loader import load_config_from_string
from ..orchestrator.runner import run_benchmark
from ..utils.logging import get_logger

log = get_logger(__name__)


async def run_benchmark_task(benchmark_uuid: str, config_yaml: str) -> None:
    """Execute a benchmark in the background and store results to database.

    Args:
        benchmark_uuid: UUID of the benchmark to run
        config_yaml: YAML configuration string
    """
    async with AsyncSessionLocal() as session:
        try:
            # Get benchmark ID for logging
            benchmark = await BenchmarkCRUD.get_by_uuid(session, benchmark_uuid)
            if not benchmark:
                log.error(f"Benchmark {benchmark_uuid} not found")
                return

            benchmark_id = benchmark.id

            # Update status to running
            await BenchmarkCRUD.update_status(
                session=session,
                uuid=benchmark_uuid,
                status="running",
                started_at=datetime.utcnow(),
            )
            await add_log(session, benchmark_id, "INFO", f"Benchmark execution started", "system")
            await session.commit()

            # Load config
            cfg = load_config_from_string(config_yaml)
            await add_log(session, benchmark_id, "INFO", f"Configuration loaded successfully", "config")
            await add_log(session, benchmark_id, "INFO", f"Config fingerprint: {cfg.fingerprint()}", "config")
            await add_log(session, benchmark_id, "INFO", f"Servers: {len(cfg.servers)}, Scenarios: {len(cfg.scenarios)}", "config")
            await session.commit()

            # Check for cancellation before starting
            if task_manager.is_cancelled(benchmark_uuid):
                await add_log(session, benchmark_id, "WARNING", "Benchmark cancelled before execution started", "system")
                await BenchmarkCRUD.update_status(
                    session=session,
                    uuid=benchmark_uuid,
                    status="cancelled",
                    completed_at=datetime.utcnow(),
                )
                await session.commit()
                task_manager.cleanup_task(benchmark_uuid)
                return

            # Create temporary output directory
            with tempfile.TemporaryDirectory() as tmpdir:
                output_dir = str(Path(tmpdir) / "results")

                # Run the benchmark
                log.info(f"Starting benchmark {benchmark_uuid}")
                await add_log(session, benchmark_id, "INFO", f"Starting benchmark execution", "orchestrator")
                await session.commit()

                start_time = time.time()

                try:
                    # Check for cancellation during execution
                    if task_manager.is_cancelled(benchmark_uuid):
                        raise asyncio.CancelledError("Benchmark cancelled by user")

                    summary = await run_benchmark(cfg, output_dir)
                    runtime_sec = time.time() - start_time

                    await add_log(session, benchmark_id, "INFO", f"Benchmark execution completed in {runtime_sec:.2f}s", "orchestrator")
                    await session.commit()

                    # Store results to database
                    await add_log(session, benchmark_id, "INFO", f"Storing results to database...", "system")
                    await _store_benchmark_results(
                        session=session,
                        benchmark_uuid=benchmark_uuid,
                        summary=summary,
                        runtime_sec=runtime_sec,
                    )
                    await add_log(session, benchmark_id, "INFO", f"Results stored successfully", "system")

                    # Update status to completed
                    await BenchmarkCRUD.update_status(
                        session=session,
                        uuid=benchmark_uuid,
                        status="completed",
                        completed_at=datetime.utcnow(),
                        runtime_sec=runtime_sec,
                    )
                    await add_log(session, benchmark_id, "INFO", f"Benchmark completed successfully", "system")
                    await session.commit()

                    log.info(f"Benchmark {benchmark_uuid} completed successfully in {runtime_sec:.2f}s")

                except asyncio.CancelledError as e:
                    log.warning(f"Benchmark {benchmark_uuid} was cancelled")

                    await add_log(session, benchmark_id, "WARNING", f"Benchmark execution cancelled: {str(e)}", "system")

                    # Update status to cancelled
                    await BenchmarkCRUD.update_status(
                        session=session,
                        uuid=benchmark_uuid,
                        status="cancelled",
                        completed_at=datetime.utcnow(),
                        runtime_sec=time.time() - start_time,
                    )
                    await session.commit()

                except Exception as e:
                    log.error(f"Benchmark {benchmark_uuid} failed: {str(e)}", exc_info=True)

                    await add_log(session, benchmark_id, "ERROR", f"Benchmark execution failed: {str(e)}", "orchestrator")

                    # Update status to failed
                    await BenchmarkCRUD.update_status(
                        session=session,
                        uuid=benchmark_uuid,
                        status="failed",
                        completed_at=datetime.utcnow(),
                        error_message=str(e),
                        runtime_sec=time.time() - start_time,
                    )
                    await session.commit()

        except Exception as e:
            log.error(f"Fatal error in benchmark task {benchmark_uuid}: {str(e)}", exc_info=True)
            # Try to log the error if we have benchmark_id
            try:
                await add_log(session, benchmark_id, "ERROR", f"Fatal error: {str(e)}", "system")
                await session.commit()
            except:
                pass
        finally:
            # Always cleanup task from manager
            task_manager.cleanup_task(benchmark_uuid)
            # Try to update status to failed
            try:
                async with AsyncSessionLocal() as error_session:
                    await BenchmarkCRUD.update_status(
                        session=error_session,
                        uuid=benchmark_uuid,
                        status="failed",
                        completed_at=datetime.utcnow(),
                        error_message=f"Fatal error: {str(e)}",
                    )
                    await error_session.commit()
            except Exception:
                log.error(f"Failed to update error status for {benchmark_uuid}")


async def _store_benchmark_results(
    session: AsyncSession,
    benchmark_uuid: str,
    summary: Dict[str, Any],
    runtime_sec: float,
) -> None:
    """Store benchmark results to database.

    Args:
        session: Database session
        benchmark_uuid: UUID of the benchmark
        summary: Summary dictionary from orchestrator
        runtime_sec: Total runtime in seconds
    """
    # Get benchmark_id from UUID
    benchmark = await BenchmarkCRUD.get_by_uuid(session, benchmark_uuid)
    if not benchmark:
        raise ValueError(f"Benchmark {benchmark_uuid} not found")

    scenarios_data = summary.get("scenarios", {})

    # Store each scenario's results
    for scenario_name, servers_data in scenarios_data.items():
        for server_name, scenario_metrics in servers_data.items():
            if not scenario_metrics:
                continue

            # Prepare metrics dict for scenario
            metrics = {
                "request_count": scenario_metrics.get("count"),
                "error_count": scenario_metrics.get("error_count"),
                "p50_ms": scenario_metrics.get("p50_ms"),
                "p90_ms": scenario_metrics.get("p90_ms"),
                "p95_ms": scenario_metrics.get("p95_ms"),
                "p99_ms": scenario_metrics.get("p99_ms"),
                "avg_ms": scenario_metrics.get("avg_ms"),
                "ttfb_p50_ms": scenario_metrics.get("ttfb_p50_ms"),
                "ttfb_p95_ms": scenario_metrics.get("ttfb_p95_ms"),
                "wait_p50_ms": scenario_metrics.get("wait_p50_ms"),
                "wait_p95_ms": scenario_metrics.get("wait_p95_ms"),
                "tokens_per_sec_output": scenario_metrics.get("tokens_per_sec_output"),
                "tokens_per_sec_input": scenario_metrics.get("tokens_per_sec_input"),
                "tokens_per_sec_total": scenario_metrics.get("tokens_per_sec_total"),
                "requests_per_sec": scenario_metrics.get("requests_per_sec"),
                "error_rate": scenario_metrics.get("error_rate"),
                "total_output_tokens": scenario_metrics.get("total_output_tokens"),
                "total_input_tokens": scenario_metrics.get("total_input_tokens"),
            }

            # Create scenario record
            scenario = await ScenarioCRUD.create(
                session=session,
                benchmark_id=benchmark.id,
                scenario_name=scenario_name,
                server_name=server_name,
                metrics=metrics,
            )

            # Store per-concurrency bucket stats
            concurrency_buckets = scenario_metrics.get("concurrency_buckets", {})
            for concurrency_str, bucket_metrics in concurrency_buckets.items():
                if not bucket_metrics:
                    continue

                # Prepare bucket metrics dict (only fields that exist in BenchmarkConcurrency model)
                bucket_data = {
                    "request_count": bucket_metrics.get("count"),
                    "error_count": bucket_metrics.get("error_count"),
                    "p50_ms": bucket_metrics.get("p50_ms"),
                    "p95_ms": bucket_metrics.get("p95_ms"),
                    "avg_ms": bucket_metrics.get("avg_ms"),
                    "tokens_per_sec_output": bucket_metrics.get("tokens_per_sec_output"),
                    "tokens_per_sec_total": bucket_metrics.get("tokens_per_sec_total"),
                    "requests_per_sec": bucket_metrics.get("requests_per_sec"),
                    "error_rate": bucket_metrics.get("error_rate"),
                }

                await ScenarioCRUD.create_concurrency_bucket(
                    session=session,
                    scenario_id=scenario.id,
                    concurrency_level=int(concurrency_str),
                    metrics=bucket_data,
                )

    await session.flush()
    log.info(f"Stored results for benchmark {benchmark_uuid}")


def start_benchmark_background(benchmark_uuid: str, config_yaml: str) -> None:
    """Start a benchmark task in the background.

    This function creates a new asyncio task that runs independently.
    It's designed to be called from FastAPI BackgroundTasks.

    Args:
        benchmark_uuid: UUID of the benchmark to run
        config_yaml: YAML configuration string
    """
    # Create a new event loop for this background task
    # This is necessary because FastAPI's BackgroundTasks runs in a thread pool
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Schedule the task
    asyncio.create_task(run_benchmark_task(benchmark_uuid, config_yaml))

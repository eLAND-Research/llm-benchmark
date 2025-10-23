"""CLI entrypoint using Typer."""
from __future__ import annotations
import typer
from pathlib import Path
import asyncio
from .config.loader import load_config
from .orchestrator.runner import run_benchmark
from .report.generator import write_report
from .utils.logging import get_logger
import json
import time

app = typer.Typer(add_completion=False, help="LLM Inference Benchmark Toolkit")
log = get_logger(__name__)


@app.command()
def validate_config(path: str = typer.Argument(..., help="YAML config path")):
    """Validate a config file and print fingerprint."""
    cfg = load_config(path)
    typer.echo("Config OK")
    typer.echo(f"Fingerprint: {cfg.fingerprint()}")
    typer.echo(f"Servers: {[s.name for s in cfg.servers]}")
    typer.echo(f"Scenarios: {[s.name for s in cfg.scenarios]}")


@app.command()
def run(
    config: str = typer.Argument(..., help="YAML config path"),
    output: str = typer.Option(None, "--output", "-o", help="Override output directory"),
    report: bool = typer.Option(True, help="Generate markdown + summary report"),
):
    """Run benchmark defined in CONFIG."""
    cfg = load_config(config)
    outdir = output or cfg.report.output_dir or f"results/run-{int(time.time())}"
    log.info("Starting benchmark -> %s", outdir)

    summary = asyncio.run(run_benchmark(cfg, outdir))
    if report:
        write_report(summary, outdir)
        log.info("Report generated at %s/report.md", outdir)
    # dump raw global summary for convenience (redundant with report generator but explicit)
    with (Path(outdir) / "global_summary_copy.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    log.info("Done")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind"),
    port: int = typer.Option(8000, help="Port to bind"),
    reload: bool = typer.Option(False, help="Enable auto-reload (development)"),
):
    """Start the LLMBench web server."""
    import uvicorn

    typer.echo(f"🚀 Starting LLMBench web server at http://{host}:{port}")
    typer.echo(f"📊 Dashboard: http://{host}:{port}/")
    typer.echo(f"📚 API Docs: http://{host}:{port}/docs")

    uvicorn.run(
        "llmbench.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":  # pragma: no cover
    app()


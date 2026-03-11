"""CLI entrypoint using Typer."""
from __future__ import annotations
import typer
from pathlib import Path
import asyncio
import logging
from .config.loader import load_config
from .orchestrator.runner import run_benchmark
from .report.generator import write_report
from .utils.logging import get_logger
import json
import time

app = typer.Typer(add_completion=False, help="LLM Inference Benchmark Toolkit")
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# qual sub-app
# ---------------------------------------------------------------------------
qual_app = typer.Typer(help="LLM 品質驗證工具")
app.add_typer(qual_app, name="qual")


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


# ---------------------------------------------------------------------------
# qual subcommands
# ---------------------------------------------------------------------------

def _setup_qual_logging() -> None:
    """Configure logging for qual pipeline commands."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


@qual_app.command("run")
def qual_run(
    config_path: str = typer.Argument(..., help="YAML 設定檔路徑"),
    output_dir: str = typer.Option(None, "-o", "--output", help="自訂輸出目錄"),
) -> None:
    """執行完整的 LLM 品質驗證 pipeline"""
    from llmbench.qual.config import load_qual_config
    from llmbench.qual.pipeline import run_qual_pipeline

    _setup_qual_logging()

    config = load_qual_config(config_path)
    if output_dir:
        config.output_dir = output_dir

    result = asyncio.run(run_qual_pipeline(config))

    # --- 印出摘要 ---
    n_items = len(result.dataset.items)
    model_names = sorted({s.model_name for s in result.scores})
    n_models = len(model_names)

    typer.echo(f"\n{'='*60}")
    typer.echo("  Qual Pipeline 完成")
    typer.echo(f"{'='*60}")
    typer.echo(f"  題目數:   {n_items}")
    typer.echo(f"  模型數:   {n_models}")

    # 各模型平均分
    for m in model_names:
        scores = [s.score for s in result.scores if s.model_name == m]
        avg = sum(scores) / len(scores) if scores else 0.0
        typer.echo(f"  {m}: 平均分 {avg:.2f}  ({len(scores)} 筆)")

    passed = result.qa_report.pass_
    status = "PASS" if passed else "FAIL"
    color = typer.colors.GREEN if passed else typer.colors.RED
    typer.secho(f"\n  驗收結果: {status}", fg=color, bold=True)
    typer.echo(f"  輸出路徑: {config.output_dir}")
    typer.echo(f"{'='*60}\n")


@qual_app.command("fetch")
def qual_fetch(
    config_path: str = typer.Argument(..., help="YAML 設定檔路徑"),
    output_dir: str = typer.Option(None, "-o", "--output", help="自訂輸出目錄"),
) -> None:
    """只抓取 TDS 資料（Phase 1: Study）"""
    from llmbench.qual.config import load_qual_config
    from llmbench.qual.pipeline import run_fetch

    _setup_qual_logging()

    config = load_qual_config(config_path)
    if output_dir:
        config.output_dir = output_dir

    materials = asyncio.run(run_fetch(config))

    typer.echo(f"\n  Phase 1 (Fetch) 完成")
    typer.echo(f"  取得素材數: {len(materials)}")
    typer.echo(f"  輸出路徑:   {config.output_dir}\n")


@qual_app.command("design")
def qual_design(
    config_path: str = typer.Argument(..., help="YAML 設定檔路徑"),
    output_dir: str = typer.Option(None, "-o", "--output", help="自訂輸出目錄"),
) -> None:
    """產生 benchmark 資料集（Phase 2: Design）"""
    from llmbench.qual.config import load_qual_config
    from llmbench.qual.pipeline import run_design

    _setup_qual_logging()

    config = load_qual_config(config_path)
    if output_dir:
        config.output_dir = output_dir

    dataset = asyncio.run(run_design(config))

    typer.echo(f"\n  Phase 2 (Design) 完成")
    typer.echo(f"  題目數:     {len(dataset.items)}")
    typer.echo(f"  任務類型:   {[t.value for t in dataset.task_types]}")
    typer.echo(f"  輸出路徑:   {config.output_dir}\n")


@qual_app.command("execute")
def qual_execute(
    config_path: str = typer.Argument(..., help="YAML 設定檔路徑"),
    output_dir: str = typer.Option(None, "-o", "--output", help="自訂輸出目錄"),
) -> None:
    """執行待測 LLM（Phase 3a）"""
    from llmbench.qual.config import load_qual_config
    from llmbench.qual.pipeline import run_execute

    _setup_qual_logging()

    config = load_qual_config(config_path)
    if output_dir:
        config.output_dir = output_dir

    dataset, responses = asyncio.run(run_execute(config))

    model_names = sorted({r.model_name for r in responses})
    typer.echo(f"\n  Phase 3a (Execute) 完成")
    typer.echo(f"  回應數:   {len(responses)}")
    typer.echo(f"  模型數:   {len(model_names)}")
    for m in model_names:
        count = sum(1 for r in responses if r.model_name == m)
        errors = sum(1 for r in responses if r.model_name == m and r.error)
        typer.echo(f"    {m}: {count} 筆 ({errors} 失敗)")
    typer.echo(f"  輸出路徑: {config.output_dir}\n")


@qual_app.command("judge")
def qual_judge(
    config_path: str = typer.Argument(..., help="YAML 設定檔路徑"),
    output_dir: str = typer.Option(None, "-o", "--output", help="自訂輸出目錄"),
) -> None:
    """執行 LLM as Judge 評分（Phase 3b）"""
    from llmbench.qual.config import load_qual_config
    from llmbench.qual.pipeline import run_judge

    _setup_qual_logging()

    config = load_qual_config(config_path)
    if output_dir:
        config.output_dir = output_dir

    dataset, responses, scores = asyncio.run(run_judge(config))

    model_names = sorted({s.model_name for s in scores})
    typer.echo(f"\n  Phase 3b (Judge) 完成")
    typer.echo(f"  評分數: {len(scores)}")
    for m in model_names:
        m_scores = [s.score for s in scores if s.model_name == m]
        avg = sum(m_scores) / len(m_scores) if m_scores else 0.0
        typer.echo(f"    {m}: 平均分 {avg:.2f}  ({len(m_scores)} 筆)")
    typer.echo(f"  輸出路徑: {config.output_dir}\n")


@qual_app.command("verify")
def qual_verify(
    config_path: str = typer.Argument(..., help="YAML 設定檔路徑"),
    output_dir: str = typer.Option(None, "-o", "--output", help="自訂輸出目錄"),
) -> None:
    """執行 UAT 驗收（Phase 4）"""
    from llmbench.qual.config import load_qual_config
    from llmbench.qual.pipeline import run_qa

    _setup_qual_logging()

    config = load_qual_config(config_path)
    if output_dir:
        config.output_dir = output_dir

    dataset, responses, scores, qa_report = asyncio.run(run_qa(config))

    passed = qa_report.pass_
    status = "PASS" if passed else "FAIL"
    color = typer.colors.GREEN if passed else typer.colors.RED

    typer.echo(f"\n  Phase 4 (Verify) 完成")
    if qa_report.issues:
        typer.echo(f"  發現問題:")
        for issue in qa_report.issues:
            typer.echo(f"    - {issue}")
    typer.secho(f"  驗收結果: {status}", fg=color, bold=True)
    typer.echo(f"  輸出路徑: {config.output_dir}\n")


@qual_app.command("report")
def qual_report(
    result_dir: str = typer.Argument(..., help="已有結果的目錄路徑"),
) -> None:
    """從已有結果目錄產生報告"""
    from llmbench.qual.report import generate_report_from_dir

    _setup_qual_logging()

    report_path = asyncio.run(generate_report_from_dir(result_dir))

    typer.echo(f"\n  報告已產生")
    typer.echo(f"  報告路徑: {report_path}\n")


if __name__ == "__main__":  # pragma: no cover
    app()


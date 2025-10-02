import asyncio
import csv
from pathlib import Path
import json
import subprocess, sys

from llmbench.config.loader import load_config
from llmbench.orchestrator.runner import run_benchmark
from llmbench.report.generator import write_report


def test_gpu_burst_throughput_and_csv(tmp_path: Path):
    cfg = load_config("config/config_gpu_burst.yaml")
    outdir = tmp_path / "burst"
    summary = asyncio.run(run_benchmark(cfg, str(outdir)))
    # generate report (creates CSV)
    write_report(summary, outdir)

    csv_path = outdir / "concurrency_throughput.csv"
    assert csv_path.exists(), "Expected concurrency_throughput.csv to be generated"

    # Load CSV rows
    with csv_path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows, "CSV should contain at least one row"

    # Check required columns
    required_cols = [
        "scenario",
        "server",
        "concurrency",
        "tokens_per_sec_output",
        "tokens_per_sec_total",
        "requests_per_sec",
    ]
    for col in required_cols:
        assert col in rows[0], f"Missing column {col} in CSV"

    # Validate positive throughput for at least one concurrency
    assert any(float(r["tokens_per_sec_output"]) > 0 for r in rows), "tokens_per_sec_output should be > 0 for at least one row"
    assert any(float(r["requests_per_sec"]) > 0 for r in rows), "requests_per_sec should be > 0 for at least one row"

    # Cross-check JSON summary concurrency buckets match CSV concurrency set
    scenario_key = cfg.scenarios[0].name
    server_key = cfg.servers[0].name
    buckets = summary["scenarios"][scenario_key][server_key]["concurrency_buckets"]
    csv_concs = set(r["concurrency"] for r in rows)
    assert csv_concs.issubset(set(buckets.keys())), "CSV concurrency levels must exist in summary buckets"


def test_cli_generates_csv(tmp_path: Path):
    # Use CLI to ensure pipeline end-to-end also creates CSV
    outdir = tmp_path / "cli_run"
    cmd = [sys.executable, "-m", "llmbench.cli", "run", "config/config_gpu_burst.yaml", "-o", str(outdir)]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    csv_path = outdir / "concurrency_throughput.csv"
    assert csv_path.exists(), "CLI run did not generate concurrency_throughput.csv"
    # Light parse check
    with csv_path.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert "tokens_per_sec_output" in header and "requests_per_sec" in header


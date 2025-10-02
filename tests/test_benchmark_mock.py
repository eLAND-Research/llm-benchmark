import asyncio
from pathlib import Path
from llmbench.config.loader import load_config
from llmbench.orchestrator.runner import run_benchmark


def test_run_mock_benchmark(tmp_path: Path):
    cfg = load_config("config/config_mock.yaml")
    out = tmp_path / "run"
    summary = asyncio.run(run_benchmark(cfg, str(out)))
    assert "scenarios" in summary
    assert "short_chat" in summary["scenarios"]
    # Ensure summary file created
    assert (out / "global_summary.json").exists()


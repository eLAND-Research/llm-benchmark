import asyncio
from pathlib import Path
from llmbench.config.loader import load_config
from llmbench.orchestrator.runner import run_benchmark


def test_concurrency_buckets(tmp_path: Path):
    cfg = load_config("config/config_mock.yaml")
    outdir = tmp_path / "conc"
    summary = asyncio.run(run_benchmark(cfg, str(outdir)))
    srv_summary = summary["scenarios"]["short_chat"]["mock_server"]
    assert "concurrency_buckets" in srv_summary, "Missing concurrency_buckets in summary"
    buckets = srv_summary["concurrency_buckets"]
    # Expect both concurrency levels from config: 1 and 2
    assert "1" in buckets and "2" in buckets, f"Unexpected buckets keys: {list(buckets.keys())}"
    total_count = srv_summary.get("count", 0)
    bucket_sum = sum(b.get("count", 0) for b in buckets.values())
    # Each request executed once per concurrency level (runs replicated), totals should match overall
    assert bucket_sum == total_count, "Bucket counts do not match overall count"


def test_streaming_approx_tokens(tmp_path: Path):
    cfg = load_config("config/config_mock_stream.yaml")
    outdir = tmp_path / "stream"
    summary = asyncio.run(run_benchmark(cfg, str(outdir)))
    srv_summary = summary["scenarios"]["short_chat"]["mock_server"]
    # Should have approximation ratio present and > 0 (since streaming fallback used)
    ratio = srv_summary.get("output_tokens_approx_ratio")
    assert ratio is not None, "Expected output_tokens_approx_ratio in streaming summary"
    assert ratio > 0, "Approx ratio should be > 0 for streaming mock"
    # Also verify concurrency buckets propagate ratio info (at least one bucket)
    buckets = srv_summary.get("concurrency_buckets", {})
    assert buckets, "Expected concurrency buckets in streaming summary"
    assert any(
        (b.get("output_tokens_approx_ratio") or 0) > 0 for b in buckets.values()
    ), "At least one concurrency bucket should have approx ratio > 0"


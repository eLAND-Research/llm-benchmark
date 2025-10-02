"""Benchmark orchestrator runner.

Coordinates scenarios, servers and load execution.
This is an MVP simplified version (no network timing yet).
"""
from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Type
from ..config.schema import RootConfig, ServerConfig
from ..scenarios.base import build_scenario, Scenario
from ..adapters.base import InferenceAdapter
from ..adapters.openai import OpenAICompatibleAdapter
from ..adapters.mock import MockAdapter
from ..loadgen.executor import LoadExecutor
from ..utils.logging import get_logger
from dataclasses import asdict
import json
from pathlib import Path
import time
import math
import random

log = get_logger(__name__)

ADAPTER_REGISTRY: Dict[str, Type[InferenceAdapter]] = {
    "openai_compatible": OpenAICompatibleAdapter,
    "mock": MockAdapter,
}


def build_adapter(server: ServerConfig) -> InferenceAdapter:
    cls = ADAPTER_REGISTRY.get(server.type)
    if not cls:
        raise ValueError(f"Unsupported adapter type: {server.type}")
    return cls(base_url=server.base_url, api_key=server.api_key, model=server.model, **server.extra)


def _categorize_error(err: Exception | str) -> str:
    msg = str(err).lower()
    if "timeout" in msg:
        return "timeout"
    if "429" in msg:
        return "http_429"
    if "5" in msg and "http" in msg:
        return "http_5xx"
    if "connection" in msg or "connect" in msg:
        return "connection"
    if "json" in msg and "decode" in msg:
        return "parse"
    if "simulated transient failure" in msg:
        return "transient"
    return "other"


async def _run_scenario_for_server(
    cfg: RootConfig, scenario: Scenario, server: ServerConfig, output_dir: Path
) -> Dict[str, Any]:
    adapter = build_adapter(server)
    s_inputs = scenario.load_inputs()
    raw_s_cfg = scenario.raw_config
    runs = raw_s_cfg.get("runs", 1)
    conc_levels: List[int] = raw_s_cfg.get("concurrency", [1])
    request_params = raw_s_cfg.get("request", {})

    if not s_inputs:
        log.warning("Scenario %s has no inputs (prompts), skipping", scenario.name)
        return {}

    # prepare tasks list (simple: replicate cycling inputs until runs)
    expanded: List[Dict[str, Any]] = []
    idx = 0
    while len(expanded) < runs:
        inp = s_inputs[idx % len(s_inputs)]
        expanded.append({"messages": [inp] if "role" in inp else inp})
        idx += 1

    all_records = []
    per_concurrency_records: Dict[int, list] = {}
    for c in conc_levels:
        log.info(
            "Scenario=%s Server=%s Concurrency=%s Runs=%s", scenario.name, server.name, c, runs
        )
        execu = LoadExecutor(concurrency=c)

        # retry helpers
        retry_cfg = cfg.retry_policy
        base_delay = retry_cfg.base_delay_ms / 1000.0
        max_attempts = max(1, retry_cfg.max_attempts)

        async def handler(payload: Dict[str, Any]):
            messages = payload.get("messages")
            stream = request_params.get("stream", False)

            attempt = 0
            last_err: Exception | None = None
            while attempt < max_attempts:
                attempt += 1
                start_local = time.time()
                try:
                    if stream and adapter.supports_stream():
                        # streaming measurement (same logic, wrapped for retry)
                        first_content_ts = None
                        content_chunk_ts: List[float] = []
                        content_accum = []
                        end_timings: Dict[str, Any] = {}
                        async for chunk in adapter.chat_stream(messages, **request_params):  # type: ignore[arg-type]
                            ts = time.time()
                            if chunk.is_end and chunk.usage and isinstance(chunk.usage, dict):
                                timings = (
                                    chunk.usage.get("timings")
                                    if isinstance(chunk.usage.get("timings"), dict)
                                    else None
                                )
                                if timings:
                                    end_timings = timings
                            if chunk.content:
                                content_accum.append(chunk.content)
                                if first_content_ts is None:
                                    first_content_ts = ts
                                content_chunk_ts.append(ts)
                        accumulated = "".join(content_accum)
                        approx_tokens = len(accumulated) // 4 if accumulated else None
                        ttfb_ms = (
                            (first_content_ts - start_local) * 1000.0
                            if first_content_ts is not None
                            else None
                        )
                        first_gap_ms = None
                        mean_interval_ms = None
                        p95_interval_ms = None
                        if len(content_chunk_ts) >= 2:
                            intervals = [
                                (content_chunk_ts[i] - content_chunk_ts[i - 1]) * 1000.0
                                for i in range(1, len(content_chunk_ts))
                            ]
                            first_gap_ms = intervals[0]
                            mean_interval_ms = sum(intervals) / len(intervals)
                            sorted_int = sorted(intervals)
                            k = int(math.ceil(0.95 * len(sorted_int))) - 1
                            k = max(0, min(k, len(sorted_int) - 1))
                            p95_interval_ms = sorted_int[k]
                        wait_ms = end_timings.get("wait_ms") if end_timings else None
                        if wait_ms is None and ttfb_ms is not None:
                            wait_ms = ttfb_ms
                        return {
                            "input_tokens": None,
                            "output_tokens": approx_tokens,
                            "output_tokens_approx": True if approx_tokens is not None else False,
                            "ttfb_ms": ttfb_ms,
                            "first_token_gap_ms": first_gap_ms,
                            "mean_token_interval_ms": mean_interval_ms,
                            "token_interval_p95_ms": p95_interval_ms,
                            "wait_ms": wait_ms,
                            "dns_ms": end_timings.get("dns_ms") if end_timings else None,
                            "connect_ms": end_timings.get("connect_ms") if end_timings else None,
                            "tls_ms": end_timings.get("tls_ms") if end_timings else None,
                            "retries": attempt - 1,
                            "error_category": None,
                        }
                    else:
                        before_call = time.time()
                        res = await adapter.chat(messages, **request_params)  # type: ignore[arg-type]
                        end_local = time.time()
                        ttfb_ms = (end_local - before_call) * 1000.0
                        timings = (
                            res.raw.get("timings", {})
                            if res.raw and isinstance(res.raw.get("timings"), dict)
                            else {}
                        )
                        if not timings and ttfb_ms is not None:
                            timings = {"wait_ms": ttfb_ms}
                        return {
                            "input_tokens": res.input_tokens,
                            "output_tokens": res.output_tokens,
                            "ttfb_ms": ttfb_ms,
                            "wait_ms": timings.get("wait_ms"),
                            "dns_ms": timings.get("dns_ms"),
                            "connect_ms": timings.get("connect_ms"),
                            "tls_ms": timings.get("tls_ms"),
                            "retries": attempt - 1,
                            "error_category": None,
                        }
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if attempt >= max_attempts:
                        break
                    # backoff with jitter
                    delay = base_delay * (2 ** (attempt - 1))
                    jitter = delay * random.uniform(0.1, 0.3)
                    await asyncio.sleep(delay + jitter)
            # fail path
            return {
                "input_tokens": None,
                "output_tokens": None,
                "ttfb_ms": None,
                "wait_ms": None,
                "retries": max_attempts - 1,
                "error_category": _categorize_error(last_err) if last_err else "unknown",
            }

        # Warmup phase (discarded)
        warm_reqs = cfg.warmup.requests if cfg.warmup else 0
        if warm_reqs > 0:
            warm_payloads = expanded[: min(len(expanded), warm_reqs)]
            log.info(
                "Warmup %s requests scenario=%s server=%s (discarding metrics)",
                len(warm_payloads),
                scenario.name,
                server.name,
            )
            try:
                await execu.run_requests(warm_payloads, handler, scenario.name, server.name)
            except Exception:  # noqa: BLE001
                pass  # warmup best-effort

        records = await execu.run_requests(expanded, handler, scenario.name, server.name)
        all_records.extend(records)
        per_concurrency_records[c] = records

    # write raw records jsonl
    per_s_dir = output_dir / f"scenario-{scenario.name}" / server.name
    per_s_dir.mkdir(parents=True, exist_ok=True)
    rec_path = per_s_dir / "requests.jsonl"
    with rec_path.open("w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(asdict(r)) + "\n")

    def aggregate(records_subset: List[Any]) -> Dict[str, Any]:
        latencies = [r.latency_ms for r in records_subset if r.error is None]
        errors = [r for r in records_subset if r.error]
        total_requests = len(records_subset)
        # token sums
        total_output_tokens = sum([r.output_tokens or 0 for r in records_subset if r.error is None])
        total_input_tokens = sum([r.input_tokens or 0 for r in records_subset if r.error is None])
        total_tokens_all = total_input_tokens + total_output_tokens
        wall_start = min([r.start_ts for r in records_subset]) if records_subset else time.time()
        wall_end = max([r.end_ts for r in records_subset]) if records_subset else wall_start
        wall_span = max(wall_end - wall_start, 1e-9)
        # Throughputs
        tokens_per_sec_output = total_output_tokens / wall_span if wall_span > 0 else 0.0
        tokens_per_sec_input = total_input_tokens / wall_span if wall_span > 0 else 0.0
        tokens_per_sec_total = total_tokens_all / wall_span if wall_span > 0 else 0.0
        # Backward compatibility: legacy field tokens_per_sec kept as output throughput
        requests_per_sec = (total_requests / wall_span) if wall_span > 0 else 0.0
        error_rate = len(errors) / total_requests if total_requests else 0.0
        ttfb_values = [r.ttfb_ms for r in records_subset if r.ttfb_ms is not None and r.error is None]
        approx_flags = [r.output_tokens_approx for r in records_subset if r.output_tokens is not None]
        wait_values = [r.wait_ms for r in records_subset if r.wait_ms is not None and r.error is None]
        error_categories: Dict[str, int] = {}
        retries_total = 0
        for r in records_subset:
            retries_total += getattr(r, "retries", 0)
            if r.error_category:
                error_categories[r.error_category] = error_categories.get(r.error_category, 0) + 1

        def pct(values: List[float], p: float) -> float:
            if not values:
                return 0.0
            sorted_vals = sorted(values)
            k = int(len(sorted_vals) * p / 100)
            k = min(max(k, 0), len(sorted_vals) - 1)
            return sorted_vals[k]

        summary_local: Dict[str, Any] = {}
        if latencies:
            summary_local = {
                "count": len(latencies),
                "error_count": len(errors),
                "p50_ms": pct(latencies, 50),
                "p90_ms": pct(latencies, 90),
                "p95_ms": pct(latencies, 95),
                "p99_ms": pct(latencies, 99),
                "avg_ms": sum(latencies) / len(latencies),
                # legacy output tokens throughput
                "tokens_per_sec": tokens_per_sec_output,
                # new detailed throughputs
                "tokens_per_sec_output": tokens_per_sec_output,
                "tokens_per_sec_input": tokens_per_sec_input,
                "tokens_per_sec_total": tokens_per_sec_total,
                "requests_per_sec": requests_per_sec,
                "total_output_tokens": total_output_tokens,
                "total_input_tokens": total_input_tokens,
                "total_tokens": total_tokens_all,
                "error_rate": error_rate,
            }
            if ttfb_values:
                summary_local.update(
                    {
                        "ttfb_p50_ms": pct(ttfb_values, 50),
                        "ttfb_p90_ms": pct(ttfb_values, 90),
                        "ttfb_p95_ms": pct(ttfb_values, 95),
                    }
                )
            if wait_values:
                summary_local.update(
                    {
                        "wait_p50_ms": pct(wait_values, 50),
                        "wait_p95_ms": pct(wait_values, 95),
                        "wait_avg_ms": sum(wait_values) / len(wait_values),
                    }
                )
        if approx_flags:
            summary_local["output_tokens_approx_ratio"] = sum(1 for a in approx_flags if a) / len(
                approx_flags
            )
        if latencies:
            summary_local.update(
                {
                    "retries_total": retries_total,
                    "retry_rate": (retries_total / len(records_subset)) if records_subset else 0.0,
                    "error_categories": error_categories,
                }
            )
        return summary_local

    # overall summary
    summary = aggregate(all_records)

    # per concurrency bucket summary
    concurrency_buckets: Dict[str, Any] = {}
    for c, recs in per_concurrency_records.items():
        concurrency_buckets[str(c)] = aggregate(recs)
    summary["concurrency_buckets"] = concurrency_buckets

    with (per_s_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


async def run_benchmark(cfg: RootConfig, output_dir: str) -> Dict[str, Any]:
    start = time.time()
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    scenarios: List[Scenario] = [build_scenario(s.model_dump()) for s in cfg.scenarios]
    server_cfgs: List[ServerConfig] = cfg.servers

    global_summary: Dict[str, Any] = {"scenarios": {}}

    for sc in scenarios:
        global_summary["scenarios"][sc.name] = {}
        for server in server_cfgs:
            log.info("Running scenario %s on server %s", sc.name, server.name)
            ssum = await _run_scenario_for_server(cfg, sc, server, outdir)
            global_summary["scenarios"][sc.name][server.name] = ssum

    global_summary["runtime_sec"] = time.time() - start
    with (outdir / "global_summary.json").open("w", encoding="utf-8") as f:
        json.dump(global_summary, f, indent=2)
    return global_summary

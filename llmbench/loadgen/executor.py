"""Async load generation executor (simplified stub).

This module manages concurrent execution of requests against an adapter.
Future extension: network timing hooks, streaming cadence measurement.
"""
from __future__ import annotations
import asyncio
import time
from typing import Any, Dict, List, Callable, Awaitable, Optional
from dataclasses import dataclass


@dataclass
class RequestRecord:
    request_id: str
    start_ts: float
    end_ts: float
    latency_ms: float
    error: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    scenario: str
    server: str
    concurrency_level: int
    # --- instrumentation fields ---
    ttfb_ms: Optional[float] = None
    first_token_gap_ms: Optional[float] = None
    mean_token_interval_ms: Optional[float] = None
    token_interval_p95_ms: Optional[float] = None
    # network placeholders (future instrumentation)
    dns_ms: Optional[float] = None
    connect_ms: Optional[float] = None
    tls_ms: Optional[float] = None
    wait_ms: Optional[float] = None
    # whether output tokens are approximate (e.g., streaming fallback)
    output_tokens_approx: bool = False
    retries: int = 0
    error_category: str | None = None


class LoadExecutor:
    def __init__(self, concurrency: int, semaphore: Optional[asyncio.Semaphore] = None):
        self.concurrency = concurrency
        self.semaphore = semaphore or asyncio.Semaphore(concurrency)

    async def run_requests(
        self,
        tasks: List[Dict[str, Any]],
        handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
        scenario: str,
        server: str,
    ) -> List[RequestRecord]:
        records: List[RequestRecord] = []
        lock = asyncio.Lock()

        async def _one(idx: int, payload: Dict[str, Any]):
            rid = f"{scenario}-{server}-{int(time.time()*1000)}-{idx}"
            async with self.semaphore:
                start = time.time()
                err: Optional[str] = None
                input_tokens = None
                output_tokens = None
                ttfb_ms = None
                first_gap = None
                mean_interval = None
                p95_interval = None
                dns_ms = connect_ms = tls_ms = wait_ms = None
                output_tokens_approx = False
                retries = 0
                error_category = None
                try:
                    result = await handler(payload)
                    input_tokens = result.get("input_tokens")
                    output_tokens = result.get("output_tokens")
                    ttfb_ms = result.get("ttfb_ms")
                    first_gap = result.get("first_token_gap_ms")
                    mean_interval = result.get("mean_token_interval_ms")
                    p95_interval = result.get("token_interval_p95_ms")
                    dns_ms = result.get("dns_ms")
                    connect_ms = result.get("connect_ms")
                    tls_ms = result.get("tls_ms")
                    wait_ms = result.get("wait_ms")
                    output_tokens_approx = bool(result.get("output_tokens_approx", False))
                    retries = int(result.get("retries", 0))
                    error_category = result.get("error_category")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    retries = 0
                    error_category = "unhandled"
                end = time.time()
                rec = RequestRecord(
                    request_id=rid,
                    start_ts=start,
                    end_ts=end,
                    latency_ms=(end - start) * 1000.0,
                    error=err,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    scenario=scenario,
                    server=server,
                    concurrency_level=self.concurrency,
                    ttfb_ms=ttfb_ms,
                    first_token_gap_ms=first_gap,
                    mean_token_interval_ms=mean_interval,
                    token_interval_p95_ms=p95_interval,
                    dns_ms=dns_ms,
                    connect_ms=connect_ms,
                    tls_ms=tls_ms,
                    wait_ms=wait_ms,
                    output_tokens_approx=output_tokens_approx,
                    retries=retries,
                    error_category=error_category,
                )
                async with lock:
                    records.append(rec)

        await asyncio.gather(*[_one(i, t) for i, t in enumerate(tasks)])
        return records

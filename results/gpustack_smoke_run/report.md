# Benchmark Report

Runtime: 134.85 sec

## Scenario: short_chat

| Server | count | error | p50(ms) | p95 | p99 | avg | wait_p50 | wait_p95 | wait_avg | tokens/s | err_rate | ttfb_p50 | ttfb_p95 | approx_ratio |
|--------|-------|-------|---------|-----|-----|-----|----------|----------|----------|----------|---------|----------|----------|--------------|
| gpustack_chat | 36 | 0 | 3751.0 | 16011.3 | 22621.9 | 5731.1 | 3750.6 | 16011.0 | 5730.8 | 166.98 | 0.000 | 3751.0 | 16011.3 | 0.00 |

### Concurrency Breakdown (gpustack_chat)
| Concurrency | count | p50(ms) | wait_p50 | tokens/s(out) | tokens/s(total) | req/s | err_rate | approx_ratio |
|-------------|-------|---------|----------|---------------|-----------------|-------|---------|--------------|
| 1 | 12 | 2681.8 | 2681.5 | 128.84 | 152.46 | 0.28 | 0.000 | 0.00 |
| 2 | 12 | 5706.3 | 5706.0 | 191.41 | 217.67 | 0.31 | 0.000 | 0.00 |
| 4 | 12 | 4120.4 | 4120.1 | 296.01 | 335.10 | 0.46 | 0.000 | 0.00 |

## Concurrency Throughput Summary

| Scenario | Server | Concurrency | Tokens/s(out) | Tokens/s(total) | Req/s | p50(ms) | p95(ms) | Err Rate | Wait p50 |
|----------|--------|-------------|---------------|-----------------|-------|---------|---------|----------|----------|
| short_chat | gpustack_chat | 1 | 128.84 | 152.46 | 0.28 | 2681.8 | 6710.2 | 0.000 | 2681.5 |
| short_chat | gpustack_chat | 2 | 191.41 | 217.67 | 0.31 | 5706.3 | 14150.5 | 0.000 | 5706.0 |
| short_chat | gpustack_chat | 4 | 296.01 | 335.10 | 0.46 | 4120.4 | 22621.9 | 0.000 | 4120.1 |

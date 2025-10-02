# Benchmark Report

Runtime: 323.65 sec

## Scenario: dual_short_chat

| Server | count | error | p50(ms) | p95 | p99 | avg | wait_p50 | wait_p95 | wait_avg | tokens/s | err_rate | ttfb_p50 | ttfb_p95 | approx_ratio |
|--------|-------|-------|---------|-----|-----|-----|----------|----------|----------|----------|---------|----------|----------|--------------|
| gpustack_chat_ext | 36 | 0 | 4327.4 | 13762.8 | 14670.3 | 5224.6 | 4327.3 | 13762.5 | 5224.3 | 154.58 | 0.000 | 4327.4 | 13762.7 | 0.00 |
| gpustack_chat_int | 36 | 0 | 5375.3 | 30026.9 | 37779.2 | 8845.5 | 5375.0 | 30026.7 | 8845.0 | 101.00 | 0.000 | 5375.3 | 30026.9 | 0.00 |

### Concurrency Breakdown (gpustack_chat_ext)
| Concurrency | count | p50(ms) | wait_p50 | tokens/s(out) | tokens/s(total) | req/s | err_rate | approx_ratio |
|-------------|-------|---------|----------|---------------|-----------------|-------|---------|--------------|
| 1 | 18 | 2559.7 | 2559.4 | 129.10 | 150.33 | 0.25 | 0.000 | 0.00 |
| 3 | 18 | 6293.3 | 6293.0 | 235.06 | 272.38 | 0.44 | 0.000 | 0.00 |

### Concurrency Breakdown (gpustack_chat_int)
| Concurrency | count | p50(ms) | wait_p50 | tokens/s(out) | tokens/s(total) | req/s | err_rate | approx_ratio |
|-------------|-------|---------|----------|---------------|-----------------|-------|---------|--------------|
| 1 | 18 | 2684.0 | 2683.6 | 99.45 | 103.42 | 0.20 | 0.000 | 0.00 |
| 3 | 18 | 7993.9 | 7993.5 | 112.13 | 116.65 | 0.22 | 0.000 | 0.00 |

## Concurrency Throughput Summary

| Scenario | Server | Concurrency | Tokens/s(out) | Tokens/s(total) | Req/s | p50(ms) | p95(ms) | Err Rate | Wait p50 |
|----------|--------|-------------|---------------|-----------------|-------|---------|---------|----------|----------|
| dual_short_chat | gpustack_chat_ext | 1 | 129.10 | 150.33 | 0.25 | 2559.7 | 10792.4 | 0.000 | 2559.4 |
| dual_short_chat | gpustack_chat_ext | 3 | 235.06 | 272.38 | 0.44 | 6293.3 | 14670.3 | 0.000 | 6293.0 |
| dual_short_chat | gpustack_chat_int | 1 | 99.45 | 103.42 | 0.20 | 2684.0 | 11735.5 | 0.000 | 2683.6 |
| dual_short_chat | gpustack_chat_int | 3 | 112.13 | 116.65 | 0.22 | 7993.9 | 37779.2 | 0.000 | 7993.5 |

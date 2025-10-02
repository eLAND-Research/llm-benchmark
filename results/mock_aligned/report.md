# Benchmark Report

Runtime: 0.10 sec

## Scenario: short_chat

| Server      | count | error | p50(ms) | p95  | p99  | avg  | wait_p50 | wait_p95 | wait_avg | tokens/s(out) | err_rate | ttfb_p50 | ttfb_p95 | approx_ratio |
| ----------- | ----- | ----- | ------- | ---- | ---- | ---- | -------- | -------- | -------- | ------------- | -------- | -------- | -------- | ------------ |
| mock_server | 12    | 0     | 11.1    | 11.1 | 11.1 | 11.1 | 11.1     | 11.1     | 11.1     | 1712.82       | 0.000    | 11.1     | 11.1     | 0.00         |

### Concurrency Breakdown (mock_server)
| Concurrency | count | p50(ms) | wait_p50 | tokens/s(out) | tokens/s(total) | req/s  | err_rate | approx_ratio |
| ----------- | ----- | ------- | -------- | ------------- | --------------- | ------ | -------- | ------------ |
| 1           | 6     | 11.1    | 11.0     | 1127.06       | 1607.93         | 90.16  | 0.000    | 0.00         |
| 2           | 6     | 11.1    | 11.1     | 2915.36       | 3877.13         | 180.33 | 0.000    | 0.00         |

## Concurrency Throughput Summary

| Scenario   | Server      | Concurrency | Tokens/s(out) | Tokens/s(total) | Req/s  | p50(ms) | p95(ms) | Err Rate | Wait p50 |
| ---------- | ----------- | ----------- | ------------- | --------------- | ------ | ------- | ------- | -------- | -------- |
| short_chat | mock_server | 1           | 1127.06       | 1607.93         | 90.16  | 11.1    | 11.1    | 0.000    | 11.0     |
| short_chat | mock_server | 2           | 2915.36       | 3877.13         | 180.33 | 11.1    | 11.1    | 0.000    | 11.1     |

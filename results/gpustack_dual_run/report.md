# Benchmark Report

Runtime: 207.01 sec

## Scenario: dual_short_chat

| Server             | count | error | p50(ms) | p95     | p99     | avg    | wait_p50 | wait_p95 | wait_avg | tokens/s(out) | err_rate | ttfb_p50 | ttfb_p95 | approx_ratio |
| ------------------ | ----- | ----- | ------- | ------- | ------- | ------ | -------- | -------- | -------- | ------------- | -------- | -------- | -------- | ------------ |
| gpt-oss-20b-gguf   | 36    | 0     | 3763.7  | 14892.6 | 17856.0 | 5605.0 | 3761.7   | 14892.5  | 5603.9   | 156.79        | 0.000    | 3763.7   | 14892.6  | 0.00         |
| gpt-oss-120b-gguf  | 36    | 0     | 1173.2  | 1238.2  | 1240.1  | 1174.5 | -        | -        | -        | 0.00          | 0.000    | -        | -        | -            |
| eland-goat-t1-gguf | 36    | 0     | 1172.6  | 1223.1  | 1234.5  | 1170.0 | -        | -        | -        | 0.00          | 0.000    | -        | -        | -            |

### Concurrency Breakdown (gpt-oss-20b-gguf)
| Concurrency | count | p50(ms) | wait_p50 | tokens/s(out) | tokens/s(total) | req/s | err_rate | approx_ratio |
| ----------- | ----- | ------- | -------- | ------------- | --------------- | ----- | -------- | ------------ |
| 1           | 18    | 4393.0  | 4392.7   | 129.98        | 148.43          | 0.22  | 0.000    | 0.00         |
| 3           | 18    | 3763.7  | 3761.7   | 236.66        | 273.11          | 0.43  | 0.000    | 0.00         |

### Concurrency Breakdown (gpt-oss-120b-gguf)
| Concurrency | count | p50(ms) | wait_p50 | tokens/s(out) | tokens/s(total) | req/s | err_rate | approx_ratio |
| ----------- | ----- | ------- | -------- | ------------- | --------------- | ----- | -------- | ------------ |
| 1           | 18    | 1162.0  | -        | 0.00          | 0.00            | 0.86  | 0.000    | -            |
| 3           | 18    | 1181.3  | -        | 0.00          | 0.00            | 2.52  | 0.000    | -            |

### Concurrency Breakdown (eland-goat-t1-gguf)
| Concurrency | count | p50(ms) | wait_p50 | tokens/s(out) | tokens/s(total) | req/s | err_rate | approx_ratio |
| ----------- | ----- | ------- | -------- | ------------- | --------------- | ----- | -------- | ------------ |
| 1           | 18    | 1157.5  | -        | 0.00          | 0.00            | 0.87  | 0.000    | -            |
| 3           | 18    | 1188.7  | -        | 0.00          | 0.00            | 2.52  | 0.000    | -            |

## Concurrency Throughput Summary

| Scenario        | Server             | Concurrency | Tokens/s(out) | Tokens/s(total) | Req/s | p50(ms) | p95(ms) | Err Rate | Wait p50 |
| --------------- | ------------------ | ----------- | ------------- | --------------- | ----- | ------- | ------- | -------- | -------- |
| dual_short_chat | gpt-oss-20b-gguf   | 1           | 129.98        | 148.43          | 0.22  | 4393.0  | 10046.1 | 0.000    | 4392.7   |
| dual_short_chat | gpt-oss-20b-gguf   | 3           | 236.66        | 273.11          | 0.43  | 3763.7  | 17856.0 | 0.000    | 3761.7   |
| dual_short_chat | gpt-oss-120b-gguf  | 1           | 0.00          | 0.00            | 0.86  | 1162.0  | 1240.1  | 0.000    | 0.0      |
| dual_short_chat | gpt-oss-120b-gguf  | 3           | 0.00          | 0.00            | 2.52  | 1181.3  | 1238.2  | 0.000    | 0.0      |
| dual_short_chat | eland-goat-t1-gguf | 1           | 0.00          | 0.00            | 0.87  | 1157.5  | 1223.1  | 0.000    | 0.0      |
| dual_short_chat | eland-goat-t1-gguf | 3           | 0.00          | 0.00            | 2.52  | 1188.7  | 1234.5  | 0.000    | 0.0      |

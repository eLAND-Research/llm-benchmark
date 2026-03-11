# LLMBench

Client-side black-box benchmarking toolkit for LLM inference servers. Measures latency, throughput, streaming cadence, and error patterns via HTTP/HTTPS — no server-side access required.

Supports OpenAI-compatible APIs, vLLM, HuggingFace TGI, SGLang, and any endpoint that speaks the OpenAI chat completions protocol.

## Features

- **Multi-server comparison** — benchmark multiple endpoints with identical prompts in a single run
- **Concurrency sweeps** — test across configurable concurrency levels to find throughput saturation points
- **Streaming metrics** — TTFB, inter-token intervals, first token gap, jitter (p95)
- **Reproducibility** — config fingerprinting via SHA256 ensures identical test conditions
- **Error analysis** — automatic categorization (timeout, rate limit, 5xx, connection, parse)
- **Retry with backoff** — exponential backoff with jitter, configurable per run
- **Web UI** — FastAPI dashboard for running benchmarks, viewing results, and exporting data
- **Structured output** — Markdown reports, JSON summaries, CSV for further analysis

## Installation

Requires Python 3.11+.

```bash
pip install -e .

# With dev dependencies
pip install -e ".[dev]"
```

## Usage

### CLI

```bash
# Validate config
llmbench validate-config config/config_mock.yaml

# Run benchmark
llmbench run config/config_mock.yaml -o results/my_run

# Start web server
llmbench serve --host 0.0.0.0 --port 8000
```

### Web UI

```bash
llmbench serve
```

- Dashboard: http://localhost:8000/
- API docs: http://localhost:8000/docs

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/benchmarks` | List benchmarks |
| POST | `/api/benchmarks` | Create from YAML |
| GET | `/api/benchmarks/{uuid}` | Benchmark details |
| GET | `/api/benchmarks/{uuid}/status` | Poll status |
| POST | `/api/benchmarks/{uuid}/run` | Trigger execution |
| POST | `/api/benchmarks/{uuid}/cancel` | Cancel running |
| DELETE | `/api/benchmarks/{uuid}` | Delete |
| GET | `/api/benchmarks/{uuid}/export` | Export (json/csv/md) |
| GET | `/api/stats` | Dashboard statistics |
| POST | `/api/validate-config` | Validate YAML |

## Configuration

```yaml
version: 1
servers:
  - name: vllm-local
    type: openai_compatible
    base_url: http://localhost:8000/v1
    model: meta-llama/Llama-3-8B

  - name: openai
    type: openai_compatible
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY
    model: gpt-4o-mini

scenarios:
  - name: short_chat
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 50
    concurrency: [1, 4, 8, 16]
    request:
      max_output_tokens: 100
      temperature: 0.7
      stream: true

warmup:
  requests: 3

retry_policy:
  strategy: exponential
  base_delay_ms: 500
  max_attempts: 3
```

API keys can be injected via `env:VAR_NAME` syntax.

## Metrics

| Category | Metrics |
|----------|---------|
| Latency | p50, p90, p95, p99 (ms) |
| Throughput | requests/sec, tokens/sec (input, output, total) |
| Streaming | TTFB, first token gap, mean/p95 inter-token interval |
| Reliability | error rate, retry rate, error category breakdown |
| Concurrency | per-bucket statistics for each concurrency level |

## Output

Each run produces:

```
results/<run_name>/
├── scenario-<name>/<server>/
│   ├── requests.jsonl    # Raw per-request data
│   └── summary.json      # Aggregated metrics
├── global_summary.json   # Cross-scenario summary
├── report.md             # Human-readable report
└── concurrency_throughput.csv
```

## Project Structure

```
llmbench/
├── adapters/       # Server adapters (OpenAI, Mock)
├── config/         # YAML schema and loader
├── loadgen/        # Async load generation
├── orchestrator/   # Benchmark execution and aggregation
├── report/         # Report generation
├── scenarios/      # Test scenario definitions
├── storage/        # SQLite backend
├── utils/          # Logging utilities
└── web/            # FastAPI web service
```

## Development

```bash
pytest -v              # Run tests
ruff check llmbench/   # Lint
mypy llmbench/         # Type check
```

## License

Apache License 2.0

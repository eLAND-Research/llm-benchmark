# LLM Inference Server Benchmark (Client-Side Black-Box)

Early skeleton (v0.1.0 draft) implementing a minimal runnable mock benchmark.

## Features (current skeleton)
- YAML config parsing (Pydantic schema)
- Scenario: chat_short (generic chat scenario loader)
- Adapters: OpenAI-compatible (basic) + Mock adapter
- Async load generation with simple latency aggregation
- Report generation (Markdown + JSON)
- CLI commands: `validate-config`, `run`

## Not Yet Implemented (planned)
Refer to `blueprint.md` for full roadmap: network timings, streaming cadence metrics, remote metrics plugins, cost model, quality evaluation (perplexity / QA), advanced aggregation.

## Quick Start (Mock)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
llmbench validate-config config/config_mock.yaml
llmbench run config/config_mock.yaml -o results/mock_run
cat results/mock_run/report.md
```

## Config Fingerprint
Fingerprint is a SHA256 of the canonical JSON dump of config → ensures reproducibility.

## Running Tests
```bash
pytest -q
```

## OpenAI-Compatible Usage (Example Skeleton)
```yaml
servers:
  - name: openai
    type: openai_compatible
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY
    model: gpt-3.5-turbo
```

Export the API key before running:
```bash
export OPENAI_API_KEY=sk-...yourkey...
```

## Directory Layout (subset)
```
llmbench/
  adapters/
  config/
  loadgen/
  orchestrator/
  report/
  scenarios/
  storage/
  utils/
config/config_mock.yaml
```

## License
Apache-2.0 (planned). Placeholder.

## Contributing
Draft stage—PRs welcome after initial stabilization. See roadmap in `blueprint.md`.


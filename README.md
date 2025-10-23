# LLMBench - LLM Inference Server Benchmark Toolkit

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://img.shields.io/badge/tests-13%2F13%20passing-brightgreen.svg)](tests/)

A comprehensive **client-side black-box benchmarking toolkit** for LLM inference servers with both **CLI** and **Web UI** interfaces. Measure latency, throughput, tokens/sec, and more without needing access to the server internals.

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-Modern%20Web%20Server-009688?style=for-the-badge&logo=fastapi" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/SQLite-Persistent%20Storage-003B57?style=for-the-badge&logo=sqlite" alt="SQLite"/>
  <img src="https://img.shields.io/badge/Tailwind-Responsive%20UI-38B2AC?style=for-the-badge&logo=tailwind-css" alt="Tailwind"/>
</p>

## ✨ Features

### Core Benchmarking
- YAML-based configuration with fingerprinting
- Multiple scenario support (chat_short, streaming, etc.)
- Adapters: OpenAI-compatible + Mock for testing
- Async load generation with concurrency control
- Detailed metrics: latency (p50/p90/p95/p99), tokens/sec, error rates
- Report generation (Markdown + JSON + CSV)

### Web Service (NEW!)
- **FastAPI-based web server** with modern UI
- **Real-time dashboard** with auto-refresh
- **Background benchmark execution** - non-blocking async tasks
- **SQLite database** for persistent storage
- **REST API** with full CRUD operations
- **Status polling** for live progress tracking
- **Responsive UI** with Tailwind CSS

### CLI Interface
- `validate-config` - Validate and fingerprint configs
- `run` - Execute benchmarks from YAML
- `serve` - Start the web server

## 🚀 Quick Start

### Option 1: Using uvx (Recommended - No Installation)
```bash
# Run directly with uvx (uv tool)
uvx --from . llmbench --help

# Validate a config
uvx --from . llmbench validate-config config/config_mock.yaml

# Run a benchmark
uvx --from . llmbench run config/config_mock.yaml

# Start the web server
uvx --from . llmbench serve
```

### Option 2: Traditional Installation
```bash
# Using uv (recommended)
uv pip install -e .

# Or using pip
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .

# Run commands
llmbench validate-config config/config_mock.yaml
llmbench run config/config_mock.yaml -o results/mock_run
llmbench serve
```

## 🌐 Web UI Usage

Start the web server:
```bash
llmbench serve
# Or with custom options
llmbench serve --host 0.0.0.0 --port 8000 --reload
```

Access the web interface:
- **Dashboard**: http://localhost:8000/
- **API Docs**: http://localhost:8000/docs
- **Create Benchmark**: http://localhost:8000/benchmarks/create

The web UI provides:
- Real-time dashboard with statistics
- Benchmark creation form with YAML editor
- Live status updates (auto-refresh)
- Benchmark history and results
- Export capabilities (JSON/CSV/Markdown)

## 📡 REST API

The web server exposes a complete REST API:

### Benchmark Management
- `GET /api/benchmarks` - List benchmarks (with pagination & filtering)
- `POST /api/benchmarks` - Create new benchmark from YAML
- `GET /api/benchmarks/{uuid}` - Get benchmark details
- `GET /api/benchmarks/{uuid}/status` - Poll benchmark status
- `POST /api/benchmarks/{uuid}/run` - Manually trigger execution
- `POST /api/benchmarks/{uuid}/cancel` - Cancel running benchmark
- `DELETE /api/benchmarks/{uuid}` - Delete benchmark
- `GET /api/benchmarks/{uuid}/export` - Export results (json/csv/markdown)

### Other Endpoints
- `GET /api/stats` - Dashboard statistics
- `POST /api/validate-config` - Validate YAML config
- `GET/POST/DELETE /api/servers` - Manage server configurations
- `GET /health` - Health check endpoint

Full API documentation available at `/docs` (Swagger UI)

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐
│   Web UI        │────▶│  FastAPI Server  │
│ (Tailwind CSS)  │     │  (Uvicorn)       │
└─────────────────┘     └────────┬─────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Background Tasks      │
                    │  (asyncio.create_task) │
                    └────────┬───────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │       Benchmark Orchestrator           │
        │  - Scenario Management                 │
        │  - Load Generation                     │
        │  - Metrics Collection                  │
        └────────┬───────────────┬───────────────┘
                 │               │
                 ▼               ▼
    ┌────────────────┐  ┌──────────────────┐
    │  Adapters      │  │  SQLite Database │
    │  - OpenAI      │  │  (async)         │
    │  - Mock        │  │  - Benchmarks    │
    │  - Custom      │  │  - Scenarios     │
    └────────────────┘  │  - Results       │
                        └──────────────────┘
```

## 🧪 Running Tests
```bash
# Run all tests
pytest -v

# Run only web tests
pytest tests/web/ -v

# Run with coverage
pytest --cov=llmbench tests/
```

All tests passing: 13/13 ✅
- 6 API endpoint tests
- 3 Database CRUD tests
- 4 End-to-end integration tests

## 📋 Example Configuration

### Basic Mock Test
```yaml
version: 1
servers:
  - name: mock_server
    type: mock
    base_url: http://localhost
    model: test-model

scenarios:
  - name: quick_test
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 10
    concurrency: [1, 2, 4]
    request:
      max_output_tokens: 50
      temperature: 0.7
```

### OpenAI-Compatible Server
```yaml
version: 1
servers:
  - name: openai
    type: openai_compatible
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY
    model: gpt-3.5-turbo

scenarios:
  - name: chat_benchmark
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 50
    concurrency: [1, 5, 10]
```

Export your API key before running:
```bash
export OPENAI_API_KEY=sk-...yourkey...
```

## 📊 Metrics Collected

- **Latency**: p50, p90, p95, p99, average (milliseconds)
- **Throughput**:
  - Requests per second
  - Input tokens per second
  - Output tokens per second
  - Total tokens per second
- **Time to First Byte (TTFB)**: p50, p90, p95
- **Error Rates**: Overall and by category
- **Retry Metrics**: Retry rate and total retries
- **Concurrency Analysis**: Per-concurrency bucket statistics

## 🎯 Use Cases

- **Performance Testing**: Measure latency and throughput under various loads
- **Capacity Planning**: Determine optimal concurrency levels
- **Cost Analysis**: Track token usage and pricing
- **A/B Testing**: Compare different models or providers
- **Regression Detection**: Monitor performance over time
- **Load Testing**: Stress test your inference infrastructure

## 📂 Project Structure

```
llmbench/
├── adapters/          # Server adapters (OpenAI, Mock, Custom)
├── config/            # Configuration schema and loader
├── loadgen/           # Async load generation engine
├── orchestrator/      # Benchmark orchestration
├── report/            # Report generation (Markdown, JSON)
├── scenarios/         # Test scenarios (chat, streaming)
├── utils/             # Utilities (logging, etc.)
└── web/              # Web service components
    ├── models.py     # SQLAlchemy ORM models
    ├── schemas.py    # Pydantic validation schemas
    ├── crud.py       # Database operations
    ├── tasks.py      # Background task runner
    ├── app.py        # FastAPI application
    ├── routes/       # API and UI routes
    └── templates/    # Jinja2 HTML templates

config/               # Example configurations
data/prompts/         # Test prompts
tests/               # Test suite
specs/               # Design documents
```

## 📝 Config Fingerprinting

Each configuration gets a SHA256 fingerprint based on its canonical JSON representation. This ensures:
- **Reproducibility**: Exact same config = exact same fingerprint
- **Tracking**: Compare runs across time
- **Verification**: Ensure benchmark integrity

## 🔧 Development

```bash
# Clone the repository
git clone <repository-url>
cd LLMBenchmark

# Install with development dependencies
uv pip install -e ".[dev]"

# Run tests
pytest -v

# Run with coverage
pytest --cov=llmbench --cov-report=html

# Lint code
ruff check .

# Format code
ruff format .

# Type checking
mypy llmbench
```

## 🚀 Production Deployment

### Using Docker (Coming Soon)
```bash
docker build -t llmbench .
docker run -p 8000:8000 llmbench serve
```

### Systemd Service
```ini
[Unit]
Description=LLMBench Web Service
After=network.target

[Service]
Type=simple
User=llmbench
WorkingDirectory=/opt/llmbench
ExecStart=/opt/llmbench/.venv/bin/llmbench serve --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the Apache License 2.0 - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- UI powered by [Tailwind CSS](https://tailwindcss.com/)
- CLI interface using [Typer](https://typer.tiangolo.com/)
- Database with [SQLAlchemy](https://www.sqlalchemy.org/)
- Package management with [uv](https://github.com/astral-sh/uv)

## 📮 Contact & Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/llmbench/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/llmbench/discussions)
- **Documentation**: See `/specs` directory for detailed design docs

---

**Note**: This is version 0.1.0 - an MVP with core features implemented. See `specs/001_webservice_plan.md` for the roadmap and planned enhancements.


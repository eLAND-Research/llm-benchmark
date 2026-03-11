# Specification: LLMBench Web Service

**Version**: 1.0
**Created**: 2025-10-21
**Status**: Draft

---

## 1. Overview

Transform the LLMBench CLI tool into a web-based service that allows users to:
- Submit benchmark jobs through a web UI
- Monitor running benchmarks in real-time
- View historical benchmark results
- Compare multiple benchmark runs
- Export results in various formats

---

## 2. Technology Stack

- **Backend Framework**: FastAPI (async support, modern Python)
- **Template Engine**: Jinja2 (built-in with FastAPI)
- **Database**: SQLite (simple, file-based, no external deps)
- **Task Queue**: Background tasks via FastAPI BackgroundTasks
- **Frontend**: HTML + Jinja2 templates + Tailwind CSS (for modern UI)
- **Charts**: Chart.js (for visualization)

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Web Browser                         │
│  (HTML/CSS/JS + Jinja2 Templates + Chart.js)           │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Server                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Routes     │  │  Background  │  │   Static     │  │
│  │   (Views)    │  │    Tasks     │  │   Files      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  SQLite Database                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Benchmarks  │  │   Requests   │  │   Servers    │  │
│  │   (Runs)     │  │  (Details)   │  │   (Config)   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              Existing LLMBench Core                     │
│  (orchestrator, adapters, scenarios, loadgen)          │
└─────────────────────────────────────────────────────────┘
```

---

## 4. Database Schema

### 4.1 Tables

#### `benchmarks` (Benchmark Runs)
```sql
CREATE TABLE benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,              -- UUID for external reference
    name TEXT NOT NULL,                      -- User-provided name
    description TEXT,                        -- Optional description
    config_fingerprint TEXT NOT NULL,        -- SHA256 from config
    config_yaml TEXT NOT NULL,               -- Full YAML config
    status TEXT NOT NULL,                    -- pending, running, completed, failed, cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    runtime_sec REAL,
    error_message TEXT,                      -- If failed
    metadata_json TEXT                       -- JSON: experiment_name, tags, etc.
);
```

#### `benchmark_scenarios` (Per-scenario results)
```sql
CREATE TABLE benchmark_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    benchmark_id INTEGER NOT NULL,
    scenario_name TEXT NOT NULL,
    server_name TEXT NOT NULL,

    -- Aggregated metrics
    request_count INTEGER,
    error_count INTEGER,
    p50_ms REAL,
    p90_ms REAL,
    p95_ms REAL,
    p99_ms REAL,
    avg_ms REAL,
    tokens_per_sec_output REAL,
    tokens_per_sec_input REAL,
    tokens_per_sec_total REAL,
    requests_per_sec REAL,
    total_output_tokens INTEGER,
    total_input_tokens INTEGER,
    total_tokens INTEGER,
    error_rate REAL,

    -- TTFB metrics
    ttfb_p50_ms REAL,
    ttfb_p90_ms REAL,
    ttfb_p95_ms REAL,

    -- Wait metrics
    wait_p50_ms REAL,
    wait_p95_ms REAL,
    wait_avg_ms REAL,

    -- Retry/error metrics
    retries_total INTEGER,
    retry_rate REAL,
    error_categories_json TEXT,              -- JSON: {timeout: 2, http_5xx: 1}

    -- Streaming metrics
    output_tokens_approx_ratio REAL,

    FOREIGN KEY (benchmark_id) REFERENCES benchmarks(id) ON DELETE CASCADE
);
```

#### `benchmark_concurrency` (Per-concurrency bucket)
```sql
CREATE TABLE benchmark_concurrency (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    concurrency_level INTEGER NOT NULL,

    -- Same metrics as benchmark_scenarios
    request_count INTEGER,
    error_count INTEGER,
    p50_ms REAL,
    p95_ms REAL,
    avg_ms REAL,
    tokens_per_sec_output REAL,
    tokens_per_sec_total REAL,
    requests_per_sec REAL,
    error_rate REAL,

    FOREIGN KEY (scenario_id) REFERENCES benchmark_scenarios(id) ON DELETE CASCADE
);
```

#### `benchmark_requests` (Individual request details)
```sql
CREATE TABLE benchmark_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    request_id TEXT NOT NULL,               -- From RequestRecord
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    latency_ms REAL NOT NULL,
    concurrency_level INTEGER,

    -- Token counts
    input_tokens INTEGER,
    output_tokens INTEGER,
    output_tokens_approx BOOLEAN,

    -- Timing details
    ttfb_ms REAL,
    first_token_gap_ms REAL,
    mean_token_interval_ms REAL,
    token_interval_p95_ms REAL,
    dns_ms REAL,
    connect_ms REAL,
    tls_ms REAL,
    wait_ms REAL,

    -- Error tracking
    error TEXT,
    error_category TEXT,
    retries INTEGER DEFAULT 0,

    FOREIGN KEY (scenario_id) REFERENCES benchmark_scenarios(id) ON DELETE CASCADE
);
```

#### `servers` (Server configurations - optional, for reuse)
```sql
CREATE TABLE servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,                      -- openai_compatible, mock, etc.
    base_url TEXT NOT NULL,
    model TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    config_json TEXT                         -- Full server config as JSON
);
```

### 4.2 Indexes

```sql
CREATE INDEX idx_benchmarks_status ON benchmarks(status);
CREATE INDEX idx_benchmarks_created_at ON benchmarks(created_at DESC);
CREATE INDEX idx_benchmarks_uuid ON benchmarks(uuid);
CREATE INDEX idx_benchmark_scenarios_benchmark_id ON benchmark_scenarios(benchmark_id);
CREATE INDEX idx_benchmark_requests_scenario_id ON benchmark_requests(scenario_id);
CREATE INDEX idx_benchmark_concurrency_scenario_id ON benchmark_concurrency(scenario_id);
```

---

## 5. API Endpoints

### 5.1 Web UI Routes (HTML responses)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Home page - dashboard with recent benchmarks |
| GET | `/benchmarks` | List all benchmarks with filters |
| GET | `/benchmarks/new` | Form to create new benchmark |
| POST | `/benchmarks` | Submit new benchmark (FormData) |
| GET | `/benchmarks/{uuid}` | View single benchmark details |
| GET | `/benchmarks/{uuid}/compare` | Compare with other benchmarks |
| DELETE | `/benchmarks/{uuid}` | Delete benchmark (with confirmation) |
| GET | `/servers` | List saved server configurations |
| GET | `/servers/new` | Form to add server config |
| POST | `/servers` | Save new server config |

### 5.2 REST API Routes (JSON responses)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/benchmarks` | List benchmarks (JSON) |
| POST | `/api/benchmarks` | Create benchmark (JSON config) |
| GET | `/api/benchmarks/{uuid}` | Get benchmark details (JSON) |
| GET | `/api/benchmarks/{uuid}/status` | Get current status (for polling) |
| POST | `/api/benchmarks/{uuid}/cancel` | Cancel running benchmark |
| DELETE | `/api/benchmarks/{uuid}` | Delete benchmark |
| GET | `/api/benchmarks/{uuid}/export` | Export results (JSON/CSV/MD) |
| GET | `/api/servers` | List servers (JSON) |
| POST | `/api/servers` | Create server config (JSON) |

### 5.3 WebSocket (Optional - Future)

| Path | Description |
|------|-------------|
| WS `/ws/benchmarks/{uuid}` | Real-time updates for running benchmark |

---

## 6. Page Specifications

### 6.1 Home Page (`/`)

**Purpose**: Dashboard overview

**Components**:
- **Header**: LLMBench logo, navigation
- **Stats Cards**:
  - Total benchmarks run
  - Running now
  - Total requests processed
  - Average throughput
- **Recent Benchmarks Table**:
  - Name, Status, Duration, Created, Actions (View/Delete)
  - Status badges (color-coded: green=completed, blue=running, red=failed)
- **Quick Actions**:
  - "New Benchmark" button (prominent)
  - "View All Benchmarks" link

### 6.2 Benchmarks List (`/benchmarks`)

**Purpose**: Browse all benchmarks with filtering

**Components**:
- **Filter Bar**:
  - Status dropdown (All, Running, Completed, Failed)
  - Date range picker
  - Search by name
  - Server filter
- **Benchmarks Table**:
  - UUID (truncated), Name, Description, Status, Servers, Runtime, Created, Actions
  - Sortable columns
  - Pagination (20 per page)
- **Bulk Actions**: Delete selected

### 6.3 New Benchmark Form (`/benchmarks/new`)

**Purpose**: Create and submit new benchmark

**Components**:
- **Form Sections**:
  1. **Basic Info**:
     - Name (required)
     - Description (optional)
  2. **Config Input** (choose one):
     - Upload YAML file
     - Paste YAML text
     - Select from saved configs
  3. **Quick Settings** (optional overrides):
     - Select server(s) from dropdown
     - Runs count
     - Concurrency levels
- **Actions**:
  - "Validate Config" button (AJAX validation)
  - "Submit Benchmark" button
  - "Save as Template" (save config for reuse)

### 6.4 Benchmark Details (`/benchmarks/{uuid}`)

**Purpose**: View comprehensive results

**Components**:
- **Header**:
  - Name, Description
  - Status badge
  - Runtime, Created/Started/Completed timestamps
  - Actions: Export (JSON/CSV/MD), Delete, Compare
- **Tabs**:
  1. **Overview**:
     - Config fingerprint
     - Metadata (experiment name, seed, etc.)
     - Summary stats cards (total requests, errors, avg latency, throughput)
  2. **Scenarios**:
     - Per-scenario tables (like current report.md)
     - Expandable concurrency breakdowns
  3. **Charts**:
     - Latency distribution (box plot)
     - Throughput by concurrency (line chart)
     - Error rate over time
     - Token generation rate
  4. **Requests** (paginated):
     - Individual request details table
     - Filters: scenario, concurrency, error status
  5. **Config**:
     - Full YAML config (syntax highlighted)
     - Fingerprint
     - Download button
- **Live Updates** (if running):
  - Progress bar
  - Current request count
  - Auto-refresh every 5s

### 6.5 Compare Page (`/benchmarks/{uuid}/compare`)

**Purpose**: Side-by-side comparison of benchmarks

**Components**:
- **Benchmark Selector**: Choose up to 4 benchmarks
- **Comparison Table**:
  - Side-by-side metrics
  - Diff highlighting (green=better, red=worse)
- **Charts**:
  - Overlaid latency percentiles
  - Throughput comparison bars
  - Error rate comparison

### 6.6 Servers Management (`/servers`)

**Purpose**: Manage reusable server configs

**Components**:
- **Servers List**: Name, Type, Base URL, Model, Actions (Edit/Delete)
- **Add Server Button**: Opens form modal
- **Form Fields**: Name, Type (dropdown), Base URL, API Key, Model, Extra config (JSON)

---

## 7. Background Task Management

### 7.1 Task Flow

```python
# Pseudocode
@app.post("/benchmarks")
async def create_benchmark(config: UploadFile, background_tasks: BackgroundTasks):
    # 1. Parse and validate config
    cfg = load_config(config)

    # 2. Create DB record with status='pending'
    benchmark = db.create_benchmark(cfg, status='pending')

    # 3. Enqueue background task
    background_tasks.add_task(run_benchmark_task, benchmark.uuid)

    # 4. Return immediately
    return {"uuid": benchmark.uuid, "status": "pending"}

async def run_benchmark_task(uuid: str):
    # 1. Update status to 'running'
    db.update_status(uuid, 'running', started_at=now())

    try:
        # 2. Run benchmark using existing orchestrator
        summary = await run_benchmark(cfg, output_dir)

        # 3. Save results to SQLite
        save_results_to_db(uuid, summary)

        # 4. Update status to 'completed'
        db.update_status(uuid, 'completed', completed_at=now())
    except Exception as e:
        # 5. Update status to 'failed'
        db.update_status(uuid, 'failed', error_message=str(e))
```

### 7.2 Progress Tracking

- Store request-level results as they complete
- Update aggregate metrics periodically
- Client polls `/api/benchmarks/{uuid}/status` for updates

---

## 8. Data Storage Strategy

### 8.1 Write Flow (During Benchmark)

1. Benchmark starts → Insert `benchmarks` row (status=running)
2. For each scenario → Insert `benchmark_scenarios` row
3. As requests complete → Insert `benchmark_requests` rows (batched)
4. After scenario completes → Update `benchmark_scenarios` with aggregates
5. Benchmark completes → Update `benchmarks` (status=completed, runtime)

### 8.2 Read Flow (Viewing Results)

1. Dashboard → Query `benchmarks` with aggregates
2. List page → Query `benchmarks` with filters + pagination
3. Details page → Join `benchmarks` + `benchmark_scenarios` + `benchmark_concurrency`
4. Requests tab → Query `benchmark_requests` with pagination
5. Charts → Aggregate `benchmark_requests` by time windows

---

## 9. Migration from Current System

### 9.1 Backward Compatibility

- Keep existing CLI commands (`llmbench run`, `validate-config`)
- CLI can optionally write to SQLite if web mode enabled
- Existing JSON/JSONL/MD outputs still generated

### 9.2 Import Existing Results

Provide utility to import old results:
```bash
llmbench import-results results/old_run/ --name "Legacy Run"
```

---

## 10. Configuration

### 10.1 Web Service Config (`web_config.yaml`)

```yaml
web:
  host: 0.0.0.0
  port: 8000
  database_path: llmbench.db
  max_concurrent_benchmarks: 3
  auto_delete_after_days: 30        # Optional cleanup
  upload_max_size_mb: 10

storage:
  results_base_path: results/web/   # Where to store result files
  keep_json_files: true              # Also save JSON/JSONL alongside DB
```

---

## 11. Directory Structure

```
llmbench/
├── web/                           # New web service code
│   ├── __init__.py
│   ├── app.py                     # FastAPI app instance
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── ui.py                  # HTML routes
│   │   └── api.py                 # JSON API routes
│   ├── models/                    # SQLAlchemy/Pydantic models
│   │   ├── __init__.py
│   │   ├── database.py            # DB setup
│   │   └── schemas.py             # Pydantic schemas
│   ├── templates/                 # Jinja2 templates
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── benchmarks_list.html
│   │   ├── benchmark_detail.html
│   │   ├── benchmark_new.html
│   │   └── components/
│   │       ├── benchmark_card.html
│   │       └── status_badge.html
│   ├── static/                    # CSS, JS, images
│   │   ├── css/
│   │   │   └── styles.css
│   │   ├── js/
│   │   │   ├── main.js
│   │   │   └── charts.js
│   │   └── img/
│   └── tasks.py                   # Background tasks
├── llmbench/                      # Existing CLI code
│   ├── cli.py                     # Keep existing CLI
│   ├── orchestrator/
│   ├── adapters/
│   └── ...
└── ...
```

---

## 12. Dependencies to Add

```toml
# Add to pyproject.toml [project.dependencies]
fastapi = ">=0.104.0"
uvicorn = {extras = ["standard"], version = ">=0.24.0"}
jinja2 = ">=3.1.0"
sqlalchemy = ">=2.0.0"
aiosqlite = ">=0.19.0"      # Async SQLite driver
python-multipart = ">=0.0.6" # For file uploads
```

---

## 13. New CLI Commands

```bash
# Start web server
llmbench serve --host 0.0.0.0 --port 8000

# Import existing results
llmbench import-results <path> --name "Run Name"

# Export from database
llmbench export-db-results <uuid> --format json
```

---

## 14. Security Considerations

### 14.1 MVP (v1)

- No authentication (local/trusted network use only)
- Input validation on config YAML
- SQL injection protection via parameterized queries
- File upload size limits
- CORS disabled by default

### 14.2 Future Enhancements

- API key authentication
- User accounts
- Rate limiting
- HTTPS support
- Role-based access control

---

## 15. Implementation Phases

### Phase 1: Core Infrastructure (Day 1-2)
- [ ] SQLite schema and migrations
- [ ] Database models (SQLAlchemy)
- [ ] Basic FastAPI app setup
- [ ] `/api/benchmarks` endpoints (CRUD)

### Phase 2: Background Tasks (Day 3)
- [ ] Background task runner
- [ ] Integrate with existing orchestrator
- [ ] Save results to DB
- [ ] Status polling endpoint

### Phase 3: Web UI (Day 4-5)
- [ ] Base template + navigation
- [ ] Home page dashboard
- [ ] Benchmarks list page
- [ ] New benchmark form
- [ ] Benchmark details page

### Phase 4: Visualization (Day 6)
- [ ] Chart.js integration
- [ ] Latency charts
- [ ] Throughput charts
- [ ] Error distribution

### Phase 5: Polish (Day 7)
- [ ] Compare functionality
- [ ] Export features
- [ ] Import legacy results
- [ ] Documentation

---

## 16. Testing Strategy

- **Unit Tests**: DB models, API endpoints
- **Integration Tests**: Full benchmark flow (submit → run → view)
- **E2E Tests**: Selenium/Playwright for UI
- **Load Tests**: Multiple concurrent benchmarks

---

## 17. Success Metrics

- [ ] Can submit benchmark via web UI
- [ ] Background task completes and saves to DB
- [ ] Can view live progress
- [ ] Can view detailed results with charts
- [ ] Can compare multiple runs
- [ ] CLI still works independently
- [ ] Page load < 2s for results with 1000s of requests

---

## 18. Open Questions

1. **WebSocket vs Polling**: Use WebSocket for real-time updates or simple polling?
   - **Recommendation**: Start with polling (simpler), add WebSocket later
2. **Chart Library**: Chart.js vs Plotly vs D3?
   - **Recommendation**: Chart.js (simpler, sufficient for MVP)
3. **ORM**: SQLAlchemy vs raw SQL?
   - **Recommendation**: SQLAlchemy (type safety, easier queries)
4. **Frontend Framework**: Plain HTML+JS vs Vue/React?
   - **Recommendation**: Plain HTML+JS with Jinja2 (simpler, SSR)

---

## 19. Example User Flows

### Flow 1: Run New Benchmark
1. User navigates to `/`
2. Clicks "New Benchmark"
3. Uploads `config.yaml` or pastes YAML
4. Clicks "Validate Config" → sees "Config OK" message
5. Clicks "Submit Benchmark"
6. Redirected to `/benchmarks/{uuid}` showing "Running" status
7. Page auto-refreshes every 5s showing progress
8. Benchmark completes → Status changes to "Completed"
9. User views charts and detailed metrics

### Flow 2: Compare Benchmarks
1. User navigates to `/benchmarks`
2. Selects 2 benchmarks using checkboxes
3. Clicks "Compare Selected"
4. Redirected to `/benchmarks/{uuid}/compare?with={uuid2}`
5. Views side-by-side comparison table and charts

---

## 20. Future Enhancements (Post-MVP)

- [ ] WebSocket for real-time updates
- [ ] Advanced filtering and search
- [ ] Saved queries/filters
- [ ] Email notifications on completion
- [ ] Slack/Discord webhooks
- [ ] CI/CD integration (GitHub Actions trigger)
- [ ] Multi-user support with authentication
- [ ] Cloud deployment (Docker + K8s)
- [ ] Scheduled recurring benchmarks
- [ ] Alerting on performance regressions
- [ ] Cost tracking and budgets

---

**End of Specification**
# Implementation Plan: LLMBench Web Service v1.0

**Based on**: `001_webservice.md`
**Target Version**: v1.0 (MVP)
**Estimated Timeline**: 7-10 days
**Created**: 2025-10-21

---

## Phase 0: Preparation & Setup (Day 0 - 0.5 days)

### Goals
- Set up project structure
- Install dependencies
- Create development environment

### Tasks

#### 0.1 Update Dependencies
```bash
# Update pyproject.toml
```
- [ ] Add FastAPI, uvicorn, jinja2, sqlalchemy, aiosqlite
- [ ] Add python-multipart for file uploads
- [ ] Run `pip install -e .[dev,web]`

#### 0.2 Create Directory Structure
```bash
llmbench/
├── web/                      # NEW
│   ├── __init__.py
│   ├── app.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── ui.py
│   │   └── api.py
│   ├── tasks.py
│   ├── templates/
│   │   ├── base.html
│   │   └── components/
│   └── static/
│       ├── css/
│       ├── js/
│       └── img/
tests/
├── web/                      # NEW
│   ├── test_api.py
│   └── test_ui.py
```

#### 0.3 Create Migration/Init Scripts
- [ ] Create `llmbench/web/init_db.py` - Database initialization
- [ ] Create `llmbench/web/migrations/` - Future schema changes

### Deliverables
- ✅ Project structure created
- ✅ Dependencies installed
- ✅ Development environment ready

---

## Phase 1: Database Layer (Day 1 - 1.5 days)

### Goals
- Implement SQLite schema
- Create ORM models
- Write database access layer
- Test CRUD operations

### Tasks

#### 1.1 Database Schema & Models (`llmbench/web/database.py`, `models.py`)

**File: `llmbench/web/database.py`**
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Async engine for SQLite
# Session factory
# Base model
```

**File: `llmbench/web/models.py`**
- [ ] Create `Base` declarative base
- [ ] Implement `Benchmark` model
  - Fields: id, uuid, name, description, config_fingerprint, config_yaml, status, timestamps, etc.
  - Methods: `to_dict()`, `from_config()`
- [ ] Implement `BenchmarkScenario` model
  - Fields: all metrics from spec
  - Relationships: `benchmark` (many-to-one)
- [ ] Implement `BenchmarkConcurrency` model
  - Relationships: `scenario` (many-to-one)
- [ ] Implement `BenchmarkRequest` model
  - Fields: all request details
  - Relationships: `scenario` (many-to-one)
- [ ] Implement `Server` model (optional for v1)
  - Fields: name, type, base_url, model, config_json

**File: `llmbench/web/init_db.py`**
- [ ] Create all tables with indexes
- [ ] Add sample data for testing (optional)

#### 1.2 Database Access Layer (DAO/Repository pattern)

**File: `llmbench/web/crud.py`**
```python
# CRUD operations for each model
class BenchmarkCRUD:
    async def create(session, data) -> Benchmark
    async def get_by_uuid(session, uuid) -> Benchmark
    async def list_all(session, filters, limit, offset) -> List[Benchmark]
    async def update_status(session, uuid, status, **kwargs)
    async def delete(session, uuid)
    async def get_with_scenarios(session, uuid) -> Benchmark (with joins)

class ScenarioCRUD:
    async def create(session, benchmark_id, data) -> BenchmarkScenario
    async def bulk_create_requests(session, scenario_id, requests)
    # etc.
```

#### 1.3 Pydantic Schemas

**File: `llmbench/web/schemas.py`**
- [ ] `BenchmarkCreate` - Input schema for creating benchmark
- [ ] `BenchmarkResponse` - Output schema with all fields
- [ ] `BenchmarkListItem` - Lightweight schema for list views
- [ ] `BenchmarkStatus` - Status-only response for polling
- [ ] `ScenarioResponse` - Scenario metrics
- [ ] Similar schemas for other models

#### 1.4 Testing

**File: `tests/web/test_database.py`**
- [ ] Test database initialization
- [ ] Test model creation and relationships
- [ ] Test CRUD operations
- [ ] Test queries with filters and pagination
- [ ] Test async operations

### Deliverables
- ✅ SQLite schema created
- ✅ ORM models implemented
- ✅ CRUD layer working
- ✅ Tests passing

---

## Phase 2: Core API Endpoints (Day 2-3 - 1.5 days)

### Goals
- Set up FastAPI application
- Implement REST API endpoints
- Add input validation
- Test API endpoints

### Tasks

#### 2.1 FastAPI App Setup

**File: `llmbench/web/app.py`**
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="LLMBench Web", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="llmbench/web/static"), name="static")

# Configure templates
templates = Jinja2Templates(directory="llmbench/web/templates")

# Include routers
from .routes import api, ui
app.include_router(api.router, prefix="/api")
app.include_router(ui.router)

# Lifespan events
@app.on_event("startup")
async def startup():
    # Initialize database
    pass

@app.on_event("shutdown")
async def shutdown():
    # Cleanup
    pass
```

**File: `llmbench/web/config.py`**
- [ ] Configuration management (database path, upload limits, etc.)
- [ ] Environment variables support

#### 2.2 API Routes Implementation

**File: `llmbench/web/routes/api.py`**

- [ ] **GET `/api/benchmarks`** - List benchmarks
  - Query params: status, limit, offset, sort
  - Response: List of BenchmarkListItem
  - Pagination support

- [ ] **POST `/api/benchmarks`** - Create benchmark
  - Request body: YAML config as JSON or multipart file
  - Validate config using existing `load_config()`
  - Create database record with status='pending'
  - Return: BenchmarkResponse with UUID

- [ ] **GET `/api/benchmarks/{uuid}`** - Get benchmark details
  - Include scenarios, concurrency buckets
  - Response: Full BenchmarkResponse

- [ ] **GET `/api/benchmarks/{uuid}/status`** - Poll status
  - Lightweight response for progress tracking
  - Response: BenchmarkStatus (status, progress, current_request_count)

- [ ] **POST `/api/benchmarks/{uuid}/cancel`** - Cancel benchmark
  - Set status to 'cancelled'
  - Stop background task (if possible)

- [ ] **DELETE `/api/benchmarks/{uuid}`** - Delete benchmark
  - Cascade delete scenarios, requests
  - Delete result files

- [ ] **GET `/api/benchmarks/{uuid}/export`** - Export results
  - Query param: format (json, csv, markdown)
  - Response: File download

- [ ] **GET `/api/servers`** - List saved servers (if time permits)
- [ ] **POST `/api/servers`** - Save server config (if time permits)

#### 2.3 Error Handling & Validation

**File: `llmbench/web/exceptions.py`**
- [ ] Custom exception classes
- [ ] Exception handlers for FastAPI
- [ ] Proper HTTP status codes

**File: `llmbench/web/validators.py`**
- [ ] YAML config validation
- [ ] UUID format validation
- [ ] File upload validation (size, type)

#### 2.4 Testing

**File: `tests/web/test_api.py`**
- [ ] Test GET /api/benchmarks (empty, with data, pagination)
- [ ] Test POST /api/benchmarks (valid config, invalid config)
- [ ] Test GET /api/benchmarks/{uuid} (exists, not found)
- [ ] Test DELETE /api/benchmarks/{uuid}
- [ ] Test error responses (400, 404, 500)

### Deliverables
- ✅ FastAPI app running
- ✅ All API endpoints implemented
- ✅ Input validation working
- ✅ API tests passing
- ✅ Can create benchmark via API (status=pending)

---

## Phase 3: Background Task Integration (Day 4 - 1 day)

### Goals
- Integrate existing benchmark orchestrator
- Run benchmarks in background
- Save results to database
- Handle errors and cancellation

### Tasks

#### 3.1 Background Task Runner

**File: `llmbench/web/tasks.py`**
```python
import asyncio
from fastapi import BackgroundTasks
from llmbench.orchestrator.runner import run_benchmark
from llmbench.config.loader import load_config

async def run_benchmark_task(uuid: str):
    """
    Background task to run benchmark and save results to DB
    """
    # 1. Get benchmark from DB
    # 2. Parse config YAML
    # 3. Update status to 'running'
    # 4. Call run_benchmark() from orchestrator
    # 5. Save results to DB (scenarios, requests)
    # 6. Update status to 'completed'
    # Handle errors, update to 'failed'
```

- [ ] Implement `run_benchmark_task(uuid)`
  - Load benchmark config from DB
  - Create output directory
  - Update status to 'running'
  - Call `run_benchmark()` from existing orchestrator
  - Parse `global_summary.json`
  - Save to database:
    - Create `BenchmarkScenario` records
    - Create `BenchmarkConcurrency` records
    - Parse request JSONL files and create `BenchmarkRequest` records
  - Update status to 'completed' with runtime
  - Handle exceptions → status='failed'

- [ ] Implement progress tracking (optional v1)
  - Update request count periodically
  - Store partial results

#### 3.2 Integration with Existing Code

**Modify: `llmbench/orchestrator/runner.py`** (optional)
- [ ] Add callback hooks for progress updates
- [ ] Add cancellation check points
- [ ] Ensure JSONL files are still written (for import compatibility)

**File: `llmbench/web/storage.py`**
- [ ] Implement `save_summary_to_db(benchmark_uuid, summary_dict)`
  - Parse summary JSON structure
  - Create scenario records
  - Create concurrency bucket records
- [ ] Implement `save_requests_to_db(scenario_id, requests_jsonl_path)`
  - Read JSONL file
  - Bulk insert request records

#### 3.3 Task Queueing

**Update: `llmbench/web/routes/api.py`**
- [ ] Modify POST `/api/benchmarks` to add background task:
  ```python
  @router.post("/benchmarks")
  async def create_benchmark(
      config: UploadFile,
      background_tasks: BackgroundTasks,
      db: AsyncSession = Depends(get_db)
  ):
      # ... validation ...
      benchmark = await crud.create_benchmark(db, ...)
      background_tasks.add_task(run_benchmark_task, benchmark.uuid)
      return {"uuid": benchmark.uuid, "status": "pending"}
  ```

#### 3.4 Testing

**File: `tests/web/test_tasks.py`**
- [ ] Test `run_benchmark_task()` with mock config
- [ ] Test database updates during task execution
- [ ] Test error handling (invalid config, adapter failure)
- [ ] Test cancellation (if implemented)
- [ ] End-to-end test: Create → Run → Save → Verify DB

### Deliverables
- ✅ Background tasks running benchmarks
- ✅ Results saved to SQLite
- ✅ Status updates working
- ✅ Error handling functional
- ✅ Can submit benchmark and see it complete

---

## Phase 4: Web UI - Core Pages (Day 5-6 - 2 days)

### Goals
- Create base templates
- Implement home page
- Implement benchmarks list
- Implement benchmark details page

### Tasks

#### 4.1 Base Template & Components

**File: `llmbench/web/templates/base.html`**
```html
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}LLMBench{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="/static/css/styles.css">
</head>
<body>
    <nav><!-- Navigation bar --></nav>
    <main class="container mx-auto">
        {% block content %}{% endblock %}
    </main>
    <script src="/static/js/main.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

**File: `llmbench/web/templates/components/status_badge.html`**
- [ ] Status badge component (color-coded by status)

**File: `llmbench/web/templates/components/benchmark_card.html`**
- [ ] Reusable benchmark card for list views

**File: `llmbench/web/static/css/styles.css`**
- [ ] Custom CSS (minimal, Tailwind does most)

**File: `llmbench/web/static/js/main.js`**
- [ ] Common utilities (AJAX helpers, form validation, etc.)

#### 4.2 Home Page (Dashboard)

**File: `llmbench/web/routes/ui.py`**
```python
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    # Get stats
    total_benchmarks = await crud.count_benchmarks(db)
    running_count = await crud.count_by_status(db, 'running')
    recent = await crud.list_benchmarks(db, limit=10)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": {...},
        "recent_benchmarks": recent
    })
```

**File: `llmbench/web/templates/index.html`**
- [ ] Header with logo
- [ ] Stats cards (4 cards: Total, Running, Completed, Avg Runtime)
- [ ] Recent benchmarks table (10 rows)
- [ ] "New Benchmark" button (prominent)
- [ ] Quick actions

#### 4.3 Benchmarks List Page

**File: `llmbench/web/routes/ui.py`**
```python
@router.get("/benchmarks", response_class=HTMLResponse)
async def list_benchmarks(
    request: Request,
    status: str = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    benchmarks = await crud.list_benchmarks(db, status, limit, offset)
    total = await crud.count_benchmarks(db, status)

    return templates.TemplateResponse("benchmarks_list.html", {
        "request": request,
        "benchmarks": benchmarks,
        "total": total,
        "page": offset // limit + 1,
        "per_page": limit
    })
```

**File: `llmbench/web/templates/benchmarks_list.html`**
- [ ] Filter bar (status dropdown, search input)
- [ ] Benchmarks table
  - Columns: UUID, Name, Description, Status, Servers, Runtime, Created, Actions
  - Sortable headers (JS)
  - Status badges
- [ ] Pagination controls
- [ ] Delete button with confirmation modal

#### 4.4 Benchmark Details Page

**File: `llmbench/web/routes/ui.py`**
```python
@router.get("/benchmarks/{uuid}", response_class=HTMLResponse)
async def benchmark_detail(
    request: Request,
    uuid: str,
    db: AsyncSession = Depends(get_db)
):
    benchmark = await crud.get_with_scenarios(db, uuid)
    if not benchmark:
        raise HTTPException(404)

    return templates.TemplateResponse("benchmark_detail.html", {
        "request": request,
        "benchmark": benchmark,
        "scenarios": benchmark.scenarios
    })
```

**File: `llmbench/web/templates/benchmark_detail.html`**
- [ ] Header (name, status, timestamps, actions)
- [ ] Tabs (Overview, Scenarios, Charts, Requests, Config)
  - **Overview Tab**: Metadata, summary stats cards
  - **Scenarios Tab**: Per-scenario tables (like report.md)
    - Expandable concurrency breakdowns
  - **Config Tab**: YAML syntax highlighted (use Prism.js)
- [ ] Export dropdown (JSON, CSV, Markdown)
- [ ] Delete button
- [ ] Auto-refresh if status='running' (JS polling every 5s)

**File: `llmbench/web/static/js/polling.js`**
- [ ] Auto-refresh logic for running benchmarks
  ```javascript
  if (status === 'running') {
      setInterval(async () => {
          const response = await fetch(`/api/benchmarks/${uuid}/status`);
          const data = await response.json();
          updateStatus(data);
      }, 5000);
  }
  ```

#### 4.5 Testing

**File: `tests/web/test_ui.py`**
- [ ] Test GET / (home page renders)
- [ ] Test GET /benchmarks (list renders)
- [ ] Test GET /benchmarks/{uuid} (detail page renders)
- [ ] Test 404 for invalid UUID
- [ ] Test UI with different benchmark statuses

### Deliverables
- ✅ Home page working
- ✅ Benchmarks list working
- ✅ Benchmark details page working
- ✅ Basic styling with Tailwind
- ✅ Navigation functional

---

## Phase 5: Web UI - Forms & Actions (Day 7 - 1 day)

### Goals
- Implement new benchmark form
- Add delete functionality
- Add export functionality

### Tasks

#### 5.1 New Benchmark Form

**File: `llmbench/web/routes/ui.py`**
```python
@router.get("/benchmarks/new", response_class=HTMLResponse)
async def new_benchmark_form(request: Request):
    return templates.TemplateResponse("benchmark_new.html", {
        "request": request
    })

@router.post("/benchmarks", response_class=HTMLResponse)
async def create_benchmark_ui(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    config_file: UploadFile = File(None),
    config_text: str = Form(None),
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    # Validate: either file or text
    # Parse config
    # Create benchmark
    # Add background task
    # Redirect to benchmark detail page
    return RedirectResponse(f"/benchmarks/{uuid}", status_code=303)
```

**File: `llmbench/web/templates/benchmark_new.html`**
- [ ] Form with sections:
  - Name (required input)
  - Description (textarea)
  - Config input (tabs: Upload File, Paste YAML)
- [ ] "Validate Config" button (AJAX validation)
  - Calls API endpoint to validate without saving
  - Shows validation errors or success message
- [ ] "Submit Benchmark" button
- [ ] Form validation (JS + backend)

**File: `llmbench/web/routes/api.py`**
- [ ] POST `/api/validate-config` - Validate config without creating benchmark
  ```python
  @router.post("/validate-config")
  async def validate_config(config: str = Body(...)):
      try:
          cfg = load_config_from_string(config)
          return {"valid": True, "fingerprint": cfg.fingerprint()}
      except Exception as e:
          return {"valid": False, "error": str(e)}
  ```

#### 5.2 Delete Functionality

**File: `llmbench/web/routes/ui.py`**
```python
@router.post("/benchmarks/{uuid}/delete")
async def delete_benchmark_ui(
    uuid: str,
    db: AsyncSession = Depends(get_db)
):
    await crud.delete_benchmark(db, uuid)
    return RedirectResponse("/benchmarks", status_code=303)
```

**File: `llmbench/web/static/js/actions.js`**
- [ ] Delete confirmation modal (before form submit)

#### 5.3 Export Functionality

**File: `llmbench/web/routes/ui.py`**
```python
from fastapi.responses import FileResponse, StreamingResponse

@router.get("/benchmarks/{uuid}/export")
async def export_benchmark(
    uuid: str,
    format: str = "json",
    db: AsyncSession = Depends(get_db)
):
    benchmark = await crud.get_with_scenarios(db, uuid)

    if format == "json":
        # Return JSON file
        return JSONResponse(benchmark.to_dict())
    elif format == "csv":
        # Generate CSV from scenarios
        return StreamingResponse(generate_csv(benchmark), media_type="text/csv")
    elif format == "markdown":
        # Generate markdown (reuse existing report generator)
        return FileResponse(...)
```

**File: `llmbench/web/export.py`**
- [ ] `generate_csv(benchmark)` - Convert to CSV format
- [ ] `generate_markdown(benchmark)` - Reuse existing `report.generator`

#### 5.4 Testing

**File: `tests/web/test_forms.py`**
- [ ] Test GET /benchmarks/new (form renders)
- [ ] Test POST /benchmarks (valid submission)
- [ ] Test POST /benchmarks (invalid config)
- [ ] Test POST /api/validate-config
- [ ] Test delete flow
- [ ] Test export (all formats)

### Deliverables
- ✅ New benchmark form working
- ✅ Can create benchmarks via UI
- ✅ Delete functionality working
- ✅ Export working (JSON, CSV, Markdown)

---

## Phase 6: Visualization & Charts (Day 8 - 1 day)

### Goals
- Add Chart.js integration
- Create latency charts
- Create throughput charts
- Add charts to benchmark details page

### Tasks

#### 6.1 Chart.js Setup

**File: `llmbench/web/templates/base.html`**
- [ ] Add Chart.js CDN
  ```html
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  ```

**File: `llmbench/web/static/js/charts.js`**
- [ ] Chart creation utilities
- [ ] Default chart configurations

#### 6.2 Chart Data API Endpoints

**File: `llmbench/web/routes/api.py`**
```python
@router.get("/benchmarks/{uuid}/chart-data/latency")
async def get_latency_chart_data(uuid: str, db: AsyncSession = Depends(get_db)):
    # Return data for latency distribution chart
    scenarios = await crud.get_scenarios(db, uuid)
    return {
        "labels": [s.scenario_name for s in scenarios],
        "datasets": [{
            "label": "p50",
            "data": [s.p50_ms for s in scenarios]
        }, {
            "label": "p95",
            "data": [s.p95_ms for s in scenarios]
        }, ...]
    }

@router.get("/benchmarks/{uuid}/chart-data/throughput")
async def get_throughput_chart_data(uuid: str, db: AsyncSession = Depends(get_db)):
    # Return data for throughput vs concurrency chart
    # ...
```

- [ ] GET `/api/benchmarks/{uuid}/chart-data/latency`
- [ ] GET `/api/benchmarks/{uuid}/chart-data/throughput`
- [ ] GET `/api/benchmarks/{uuid}/chart-data/errors`

#### 6.3 Charts Implementation

**File: `llmbench/web/templates/benchmark_detail.html`**
- [ ] Add Charts tab with canvas elements
  ```html
  <div id="charts-tab">
      <canvas id="latencyChart"></canvas>
      <canvas id="throughputChart"></canvas>
      <canvas id="errorChart"></canvas>
  </div>
  ```

**File: `llmbench/web/static/js/benchmark_charts.js`**
- [ ] Create latency distribution chart (bar chart)
  - X: Scenarios
  - Y: Latency (ms)
  - Multiple bars: p50, p90, p95, p99

- [ ] Create throughput chart (line chart)
  - X: Concurrency level
  - Y: Tokens/sec
  - Lines per scenario

- [ ] Create error rate chart (pie/doughnut chart)
  - Error categories distribution

#### 6.4 Testing

**File: `tests/web/test_charts.py`**
- [ ] Test chart data API endpoints
- [ ] Test chart rendering (Selenium/Playwright if time permits)

### Deliverables
- ✅ Charts showing on details page
- ✅ Latency, throughput, error charts working
- ✅ Interactive (hover tooltips, legends)

---

## Phase 7: Polish & CLI Integration (Day 9 - 1 day)

### Goals
- Add CLI command to start web server
- Improve error handling
- Add loading states
- Documentation
- Final testing

### Tasks

#### 7.1 CLI Integration

**File: `llmbench/cli.py`**
```python
@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind"),
    port: int = typer.Option(8000, help="Port to bind"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
):
    """Start the LLMBench web server."""
    import uvicorn
    uvicorn.run(
        "llmbench.web.app:app",
        host=host,
        port=port,
        reload=reload
    )
```

- [ ] Add `serve` command
- [ ] Add help text
- [ ] Test: `llmbench serve --port 8000`

#### 7.2 Error Handling & UX Improvements

**File: `llmbench/web/templates/error.html`**
- [ ] Create error page template (404, 500)

**File: `llmbench/web/app.py`**
- [ ] Add exception handlers
  ```python
  @app.exception_handler(404)
  async def not_found_handler(request, exc):
      return templates.TemplateResponse("error.html", {...}, status_code=404)
  ```

**File: `llmbench/web/static/js/ui.js`**
- [ ] Add loading spinners for AJAX requests
- [ ] Add toast notifications for actions (success/error)
- [ ] Form validation feedback

#### 7.3 Database Migration Script

**File: `llmbench/web/init_db.py`**
- [ ] Make runnable as CLI: `python -m llmbench.web.init_db`
- [ ] Add confirmation prompts
- [ ] Add data migration from old results (optional)

#### 7.4 Documentation

**File: `docs/webservice.md`**
- [ ] User guide: How to start server
- [ ] How to create benchmarks via UI
- [ ] How to view results
- [ ] API documentation (basic)

**File: `README.md`** (update)
- [ ] Add web service quick start
- [ ] Add screenshot (optional)

**File: `llmbench/web/README.md`**
- [ ] Developer guide
- [ ] Architecture overview
- [ ] Database schema diagram

#### 7.5 Final Testing & Fixes

**File: `tests/web/test_integration.py`**
- [ ] End-to-end test: Full benchmark flow via UI
- [ ] Test concurrent benchmarks
- [ ] Test pagination with many results
- [ ] Load test: 1000+ requests in DB

**Manual Testing Checklist:**
- [ ] Start server: `llmbench serve`
- [ ] Create benchmark via UI
- [ ] View running benchmark (auto-refresh)
- [ ] View completed benchmark (all tabs)
- [ ] Export results
- [ ] Delete benchmark
- [ ] Filter benchmarks
- [ ] Test on different browsers (Chrome, Firefox)
- [ ] Test responsive design (mobile/tablet)

#### 7.6 Performance Optimization

- [ ] Add database indexes (if not done)
- [ ] Optimize query joins
- [ ] Add caching headers for static files
- [ ] Compress responses (gzip)

### Deliverables
- ✅ `llmbench serve` command working
- ✅ Error handling robust
- ✅ Documentation complete
- ✅ All tests passing
- ✅ Ready for demo/release

---

## Phase 8: Optional Enhancements (Day 10+)

### If Time Permits

#### 8.1 Compare Functionality
- [ ] Select multiple benchmarks
- [ ] Side-by-side comparison page
- [ ] Diff highlighting

#### 8.2 Server Management
- [ ] CRUD for saved servers
- [ ] Reuse servers in new benchmarks

#### 8.3 Advanced Filtering
- [ ] Date range picker
- [ ] Multi-select filters
- [ ] Saved filters

#### 8.4 Import Legacy Results
- [ ] CLI command: `llmbench import-results <path>`
- [ ] Parse existing JSON/JSONL files
- [ ] Insert into database

---

## Testing Strategy

### Unit Tests
- **Database**: Model creation, CRUD operations
- **API**: All endpoints (happy path + errors)
- **Tasks**: Background task execution
- **Utilities**: Validators, exporters

### Integration Tests
- **End-to-end**: Create → Run → View → Export → Delete
- **Concurrent**: Multiple benchmarks running
- **Large datasets**: 1000+ requests

### Manual Testing
- **UI**: All pages and interactions
- **Cross-browser**: Chrome, Firefox, Safari
- **Responsive**: Mobile, tablet, desktop

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Background tasks fail silently | High | Robust error handling, logging, status updates |
| Database locks with concurrent writes | Medium | Use WAL mode for SQLite, batch inserts |
| Large request datasets (10K+) slow queries | Medium | Pagination, indexes, lazy loading |
| Chart.js performance with many data points | Low | Limit data points, use sampling for large datasets |
| File uploads malicious content | Medium | Validate YAML, size limits, sanitization |

---

## Success Criteria

### Must Have (v1.0 Release)
- ✅ Can submit benchmark via web UI
- ✅ Background task runs and completes
- ✅ Results stored in SQLite
- ✅ Can view detailed results with metrics
- ✅ Charts display correctly
- ✅ Export to JSON/CSV/Markdown works
- ✅ Delete functionality works
- ✅ `llmbench serve` command works
- ✅ All tests pass

### Nice to Have
- Compare functionality
- Server management
- Import legacy results
- WebSocket real-time updates
- Advanced filters

---

## Daily Breakdown

| Day | Phase | Main Deliverable |
|-----|-------|------------------|
| 0 | Prep | Project structure, dependencies installed |
| 1 | DB Layer | Database schema, models, CRUD working |
| 2-3 | Core API | REST API endpoints functional |
| 4 | Background Tasks | Benchmarks run in background, save to DB |
| 5-6 | Web UI Core | Home, list, detail pages working |
| 7 | Web UI Forms | New benchmark form, delete, export |
| 8 | Charts | Visualizations on detail page |
| 9 | Polish | CLI integration, docs, testing |
| 10+ | Optional | Compare, import, advanced features |

---

## Post-Launch Roadmap

### v1.1 (Week 2-3)
- WebSocket real-time updates
- Compare functionality
- Import legacy results
- Advanced filtering

### v1.2 (Month 2)
- User authentication
- API keys
- Multi-user support
- Scheduled benchmarks

### v2.0 (Quarter 2)
- Alerting on regressions
- CI/CD integration (GitHub Actions)
- Cost tracking and budgets
- Cloud deployment guides

---

**End of Implementation Plan**
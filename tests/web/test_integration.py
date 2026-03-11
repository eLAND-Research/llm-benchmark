"""Integration tests for benchmark execution."""
import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from llmbench.web.app import app
from llmbench.web.database import init_db, drop_db


@pytest_asyncio.fixture
async def client():
    """Create test client."""
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await drop_db()


@pytest.mark.asyncio
async def test_benchmark_full_workflow(client: AsyncClient):
    """Test creating and running a benchmark end-to-end."""
    # Create a benchmark with mock adapter (fast execution)
    config_yaml = """
version: 1
servers:
  - name: test_mock
    type: mock
    base_url: http://test
    model: test-model
scenarios:
  - name: quick_test
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 5
    concurrency: [1, 2]
"""

    # Create benchmark with auto_run=True
    response = await client.post(
        "/api/benchmarks",
        data={
            "name": "Integration Test Benchmark",
            "description": "End-to-end test",
            "config_text": config_yaml,
            "auto_run": "true",
        },
    )

    assert response.status_code == 200
    data = response.json()
    benchmark_uuid = data["uuid"]
    assert data["status"] == "pending"  # Initially pending

    # Poll status until completed (with timeout)
    max_attempts = 30  # 30 seconds max
    for attempt in range(max_attempts):
        await asyncio.sleep(1)

        status_response = await client.get(f"/api/benchmarks/{benchmark_uuid}/status")
        assert status_response.status_code == 200
        status_data = status_response.json()

        if status_data["status"] in ["completed", "failed"]:
            break
    else:
        pytest.fail("Benchmark did not complete within timeout")

    # Verify final status
    assert status_data["status"] == "completed", f"Expected completed, got {status_data['status']}"

    # Get full benchmark details
    detail_response = await client.get(f"/api/benchmarks/{benchmark_uuid}")
    assert detail_response.status_code == 200
    detail_data = detail_response.json()

    assert detail_data["status"] == "completed"
    assert detail_data["runtime_sec"] is not None
    assert detail_data["runtime_sec"] > 0

    # Verify scenarios were stored
    scenarios = detail_data["scenarios"]
    assert len(scenarios) > 0

    # Check scenario has metrics
    scenario = scenarios[0]
    assert scenario["scenario_name"] == "quick_test"
    assert scenario["server_name"] == "test_mock"
    # request_count is 10 because runs=5 across concurrency=[1,2] = 5+5=10
    assert scenario["request_count"] == 10
    assert scenario["p50_ms"] is not None
    assert scenario["tokens_per_sec_output"] is not None


@pytest.mark.asyncio
async def test_benchmark_manual_run(client: AsyncClient):
    """Test creating a benchmark without auto_run and then manually starting it."""
    config_yaml = """
version: 1
servers:
  - name: test_mock_2
    type: mock
    base_url: http://test
    model: test-model
scenarios:
  - name: manual_test
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 3
"""

    # Create benchmark with auto_run=False
    response = await client.post(
        "/api/benchmarks",
        data={
            "name": "Manual Run Test",
            "description": "Test manual execution",
            "config_text": config_yaml,
            "auto_run": "false",
        },
    )

    assert response.status_code == 200
    data = response.json()
    benchmark_uuid = data["uuid"]
    assert data["status"] == "pending"

    # Wait a bit to ensure it doesn't auto-start
    await asyncio.sleep(2)

    # Verify still pending
    status_response = await client.get(f"/api/benchmarks/{benchmark_uuid}/status")
    assert status_response.json()["status"] == "pending"

    # Manually start the benchmark
    run_response = await client.post(f"/api/benchmarks/{benchmark_uuid}/run")
    assert run_response.status_code == 200

    # Poll until completed
    max_attempts = 20
    for attempt in range(max_attempts):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/benchmarks/{benchmark_uuid}/status")
        if status_response.json()["status"] in ["completed", "failed"]:
            break

    # Verify completed
    final_status = status_response.json()
    assert final_status["status"] == "completed"


@pytest.mark.asyncio
async def test_benchmark_with_invalid_config(client: AsyncClient):
    """Test that benchmarks with invalid configs fail gracefully."""
    # Create benchmark with invalid config (missing required fields)
    config_yaml = """
version: 1
servers:
  - name: test_invalid
    type: nonexistent_type
    base_url: http://test
scenarios:
  - name: will_fail
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 1
"""

    response = await client.post(
        "/api/benchmarks",
        data={
            "name": "Invalid Config Test",
            "config_text": config_yaml,
            "auto_run": "true",
        },
    )

    assert response.status_code == 200
    benchmark_uuid = response.json()["uuid"]

    # Poll status - should fail
    max_attempts = 10
    for attempt in range(max_attempts):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/benchmarks/{benchmark_uuid}/status")
        status = status_response.json()["status"]
        if status == "failed":
            break
    else:
        pytest.fail("Benchmark should have failed with invalid adapter type")

    # Get details and verify error message
    detail_response = await client.get(f"/api/benchmarks/{benchmark_uuid}")
    detail_data = detail_response.json()
    assert detail_data["status"] == "failed"
    assert detail_data["error_message"] is not None
    assert "adapter" in detail_data["error_message"].lower() or "type" in detail_data["error_message"].lower()


@pytest.mark.asyncio
async def test_list_benchmarks_with_various_statuses(client: AsyncClient):
    """Test listing benchmarks filters by status correctly."""
    # Create benchmarks with different outcomes
    mock_config = """
version: 1
servers:
  - name: test_mock
    type: mock
    base_url: http://test
    model: test-model
scenarios:
  - name: list_test
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 2
"""

    # Create completed benchmark
    response1 = await client.post(
        "/api/benchmarks",
        data={"name": "Completed Benchmark", "config_text": mock_config, "auto_run": "true"},
    )
    uuid1 = response1.json()["uuid"]

    # Create pending benchmark (no auto_run)
    response2 = await client.post(
        "/api/benchmarks",
        data={"name": "Pending Benchmark", "config_text": mock_config, "auto_run": "false"},
    )
    uuid2 = response2.json()["uuid"]

    # Wait for first one to complete
    for _ in range(15):
        await asyncio.sleep(1)
        status = await client.get(f"/api/benchmarks/{uuid1}/status")
        if status.json()["status"] == "completed":
            break

    # List all benchmarks
    all_response = await client.get("/api/benchmarks")
    assert all_response.status_code == 200
    all_data = all_response.json()
    assert len(all_data) >= 2

    # List only completed
    completed_response = await client.get("/api/benchmarks?status=completed")
    completed_data = completed_response.json()
    assert any(b["uuid"] == uuid1 for b in completed_data)

    # List only pending
    pending_response = await client.get("/api/benchmarks?status=pending")
    pending_data = pending_response.json()
    assert any(b["uuid"] == uuid2 for b in pending_data)

"""Test API endpoints."""
import pytest
import pytest_asyncio
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
async def test_health_check(client: AsyncClient):
    """Test health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_list_benchmarks_empty(client: AsyncClient):
    """Test listing benchmarks when database is empty."""
    response = await client.get("/api/benchmarks")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_create_benchmark(client: AsyncClient):
    """Test creating a benchmark via API."""
    config_yaml = """
version: 1
servers:
  - name: test_server
    type: mock
    base_url: http://test
    model: test-model
scenarios:
  - name: test_scenario
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 5
"""

    response = await client.post(
        "/api/benchmarks",
        data={
            "name": "Test Benchmark",
            "description": "A test benchmark",
            "config_text": config_yaml,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Benchmark"
    assert data["status"] == "pending"
    assert "uuid" in data


@pytest.mark.asyncio
async def test_get_benchmark_not_found(client: AsyncClient):
    """Test getting a non-existent benchmark."""
    response = await client.get("/api/benchmarks/nonexistent-uuid")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_validate_config_valid(client: AsyncClient):
    """Test config validation endpoint with valid config."""
    config_yaml = """
version: 1
servers:
  - name: test
    type: mock
    base_url: http://test
scenarios:
  - name: test
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 1
"""

    response = await client.post(
        "/api/validate-config",
        data={"config_text": config_yaml},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert "fingerprint" in data


@pytest.mark.asyncio
async def test_validate_config_invalid(client: AsyncClient):
    """Test config validation with invalid YAML."""
    response = await client.post(
        "/api/validate-config",
        data={"config_text": "invalid: yaml: content: [[["},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "error" in data

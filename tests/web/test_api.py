"""Test API endpoints."""
import json
from io import BytesIO

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from openpyxl import load_workbook
from llmbench.web.app import app
from llmbench.web.database import init_db, drop_db
from llmbench.web.crud import ChallengeCRUD
from llmbench.web.database import AsyncSessionLocal


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


@pytest.mark.asyncio
async def test_import_ptt_movie_challenge(client: AsyncClient, monkeypatch):
    """Test importing PTT Movie articles into a challenge."""
    from llmbench.qual.schemas import RawMaterial

    def fake_load_ptt_board_materials(**kwargs):
        assert kwargs["board"] == "movie"
        assert kwargs["pages"] == 2
        return [
            RawMaterial(
                source_category="ptt/movie",
                title="[好雷] 測試電影",
                content="【主題】\n這是一篇文章\n\n【留言（共 1 則）】\n1. 推 很好看",
                keyword="movie",
                month_range={"start": "202604", "end": "202604"},
            )
        ]

    monkeypatch.setattr(
        "llmbench.qual.ptt_source.load_ptt_board_materials",
        fake_load_ptt_board_materials,
    )

    response = await client.post(
        "/api/challenges/import/ptt-movie",
        data={
            "name": "PTT Movie Import",
            "description": "test import",
            "board": "movie",
            "pages": "2",
            "keyword": "movie",
            "combine_pushes": "true",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "PTT Movie Import"
    assert data["task_type"] == "ptt_movie"
    assert data["row_count"] == 1

    detail = await client.get(f"/api/challenges/{data['uuid']}/download")
    assert detail.status_code == 200
    row = json.loads(detail.text.strip())
    assert row["source_category"] == "ptt/movie"
    assert row["month"] == "202604"


@pytest.mark.asyncio
async def test_export_questions_downloads_xlsx_for_qa(client: AsyncClient):
    """Test exporting participant questions as XLSX for QA challenges."""
    data_jsonl = "\n".join([
        json.dumps({"title": "文章一", "content": "內容一"}, ensure_ascii=False),
        json.dumps({"title": "文章二", "content": "內容二"}, ensure_ascii=False),
    ])

    response = await client.post(
        "/api/challenges",
        data={
            "name": "QA Export",
            "description": "xlsx export test",
            "task_type": "qa",
        },
        files={
            "data_file": ("questions.jsonl", data_jsonl.encode("utf-8"), "application/x-ndjson"),
        },
    )
    assert response.status_code == 200
    challenge = response.json()

    generated_results = "\n".join([
        json.dumps({
            "task_type": "qa",
            "title": "文章一",
            "reference_answer": {"question": "問題一"},
        }, ensure_ascii=False),
        json.dumps({
            "task_type": "qa",
            "title": "文章二",
            "reference_answer": {"question": "問題二"},
        }, ensure_ascii=False),
    ])

    async with AsyncSessionLocal() as session:
        saved = await ChallengeCRUD.save_results(session, challenge["uuid"], generated_results)
        assert saved is not None
        await session.commit()

    export_response = await client.get(f"/api/challenges/{challenge['uuid']}/export-questions")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "QA_Export_questions.xlsx" in export_response.headers["content-disposition"]

    workbook = load_workbook(BytesIO(export_response.content))
    sheet = workbook.active
    assert sheet.title == "Questions"
    assert [cell.value for cell in sheet[1]] == ["#", "文章標題", "問題", "回答"]
    assert [sheet["A2"].value, sheet["B2"].value, sheet["C2"].value, sheet["D2"].value] == [1, "文章一", "問題一", ""]
    assert [sheet["A3"].value, sheet["B3"].value, sheet["C3"].value, sheet["D3"].value] == [2, "文章二", "問題二", ""]

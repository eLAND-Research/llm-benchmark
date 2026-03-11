"""Test database operations."""
import pytest
import pytest_asyncio
import uuid
from llmbench.web.database import AsyncSessionLocal, init_db, drop_db
from llmbench.web import models
from llmbench.web.crud import BenchmarkCRUD


@pytest_asyncio.fixture
async def db_session():
    """Create a test database session."""
    await init_db()
    async with AsyncSessionLocal() as session:
        yield session
    await drop_db()


@pytest.mark.asyncio
async def test_create_benchmark(db_session):
    """Test creating a benchmark."""
    benchmark = await BenchmarkCRUD.create(
        session=db_session,
        name="Test Benchmark",
        description="Test description",
        config_yaml="version: 1",
        config_fingerprint="abc123",
    )

    assert benchmark.uuid is not None
    assert benchmark.name == "Test Benchmark"
    assert benchmark.status == "pending"
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_benchmarks(db_session):
    """Test listing benchmarks."""
    # Create a few benchmarks
    for i in range(3):
        await BenchmarkCRUD.create(
            session=db_session,
            name=f"Benchmark {i}",
            description=None,
            config_yaml="version: 1",
            config_fingerprint=f"fp{i}",
        )
    await db_session.commit()

    # List them
    benchmarks = await BenchmarkCRUD.list_all(db_session, limit=10)
    assert len(benchmarks) == 3


@pytest.mark.asyncio
async def test_update_status(db_session):
    """Test updating benchmark status."""
    from datetime import datetime

    benchmark = await BenchmarkCRUD.create(
        session=db_session,
        name="Test",
        description=None,
        config_yaml="version: 1",
        config_fingerprint="test",
    )
    await db_session.commit()

    # Update status
    await BenchmarkCRUD.update_status(
        session=db_session,
        uuid=benchmark.uuid,
        status="running",
        started_at=datetime.utcnow(),
    )
    await db_session.commit()

    # Verify
    updated = await BenchmarkCRUD.get_by_uuid(db_session, benchmark.uuid)
    assert updated.status == "running"
    assert updated.started_at is not None

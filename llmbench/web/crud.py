"""CRUD operations for database models."""
import uuid as uuid_lib
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Benchmark, BenchmarkScenario, BenchmarkConcurrency, BenchmarkRequest, Server


class BenchmarkCRUD:
    """CRUD operations for benchmarks."""

    @staticmethod
    async def create(
        session: AsyncSession,
        name: str,
        description: Optional[str],
        config_yaml: str,
        config_fingerprint: str,
        metadata_json: Optional[str] = None,
        parent_uuid: Optional[str] = None,
        run_number: int = 1,
    ) -> Benchmark:
        """Create a new benchmark."""
        benchmark = Benchmark(
            uuid=str(uuid_lib.uuid4()),
            name=name,
            description=description,
            config_yaml=config_yaml,
            config_fingerprint=config_fingerprint,
            status="pending",
            metadata_json=metadata_json,
            parent_uuid=parent_uuid,
            run_number=run_number,
        )
        session.add(benchmark)
        await session.flush()
        return benchmark

    @staticmethod
    async def get_by_uuid(session: AsyncSession, uuid: str) -> Optional[Benchmark]:
        """Get benchmark by UUID."""
        result = await session.execute(
            select(Benchmark).where(Benchmark.uuid == uuid)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_with_scenarios(session: AsyncSession, uuid: str) -> Optional[Benchmark]:
        """Get benchmark with scenarios loaded."""
        result = await session.execute(
            select(Benchmark)
            .options(selectinload(Benchmark.scenarios))
            .where(Benchmark.uuid == uuid)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_all(
        session: AsyncSession,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Benchmark]:
        """List benchmarks with optional filters."""
        query = select(Benchmark).order_by(Benchmark.created_at.desc())

        if status:
            query = query.where(Benchmark.status == status)

        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count_all(
        session: AsyncSession,
        status: Optional[str] = None,
    ) -> int:
        """Count benchmarks."""
        query = select(func.count(Benchmark.id))

        if status:
            query = query.where(Benchmark.status == status)

        result = await session.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def update_status(
        session: AsyncSession,
        uuid: str,
        status: str,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        runtime_sec: Optional[float] = None,
        error_message: Optional[str] = None,
    ):
        """Update benchmark status and timestamps."""
        benchmark = await BenchmarkCRUD.get_by_uuid(session, uuid)
        if not benchmark:
            raise ValueError(f"Benchmark {uuid} not found")

        benchmark.status = status
        if started_at:
            benchmark.started_at = started_at
        if completed_at:
            benchmark.completed_at = completed_at
        if runtime_sec is not None:
            benchmark.runtime_sec = runtime_sec
        if error_message:
            benchmark.error_message = error_message

        await session.flush()

    @staticmethod
    async def delete(session: AsyncSession, uuid: str):
        """Delete benchmark and all related data (cascade)."""
        await session.execute(
            delete(Benchmark).where(Benchmark.uuid == uuid)
        )
        await session.flush()

    @staticmethod
    async def get_history(session: AsyncSession, uuid: str) -> List[Benchmark]:
        """Get all benchmarks in the same history chain (same root parent).

        Returns benchmarks ordered by run_number (newest first).
        """
        benchmark = await BenchmarkCRUD.get_by_uuid(session, uuid)
        if not benchmark:
            return []

        # Find the root benchmark (the one without a parent)
        root_uuid = uuid
        if benchmark.parent_uuid:
            # Traverse up to find the root
            current = benchmark
            while current.parent_uuid:
                parent = await BenchmarkCRUD.get_by_uuid(session, current.parent_uuid)
                if not parent:
                    break
                current = parent
            root_uuid = current.uuid

        # Get all benchmarks with this root as parent OR the root itself
        result = await session.execute(
            select(Benchmark)
            .where(
                (Benchmark.uuid == root_uuid) |
                (Benchmark.parent_uuid == root_uuid) |
                (Benchmark.parent_uuid == uuid)
            )
            .order_by(Benchmark.run_number.desc(), Benchmark.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_next_run_number(session: AsyncSession, parent_uuid: str) -> int:
        """Get the next run number for a benchmark chain."""
        result = await session.execute(
            select(func.max(Benchmark.run_number))
            .where(
                (Benchmark.uuid == parent_uuid) |
                (Benchmark.parent_uuid == parent_uuid)
            )
        )
        max_run = result.scalar()
        return (max_run or 0) + 1


class ScenarioCRUD:
    """CRUD operations for scenarios."""

    @staticmethod
    async def create(
        session: AsyncSession,
        benchmark_id: int,
        scenario_name: str,
        server_name: str,
        metrics: Dict[str, Any],
    ) -> BenchmarkScenario:
        """Create a scenario record."""
        scenario = BenchmarkScenario(
            benchmark_id=benchmark_id,
            scenario_name=scenario_name,
            server_name=server_name,
            **metrics
        )
        session.add(scenario)
        await session.flush()
        return scenario

    @staticmethod
    async def bulk_create_requests(
        session: AsyncSession,
        scenario_id: int,
        requests: List[Dict[str, Any]],
    ):
        """Bulk create request records."""
        request_objs = [
            BenchmarkRequest(scenario_id=scenario_id, **req)
            for req in requests
        ]
        session.add_all(request_objs)
        await session.flush()

    @staticmethod
    async def create_concurrency_bucket(
        session: AsyncSession,
        scenario_id: int,
        concurrency_level: int,
        metrics: Dict[str, Any],
    ) -> BenchmarkConcurrency:
        """Create a concurrency bucket record."""
        bucket = BenchmarkConcurrency(
            scenario_id=scenario_id,
            concurrency_level=concurrency_level,
            **metrics
        )
        session.add(bucket)
        await session.flush()
        return bucket


class ServerCRUD:
    """CRUD operations for servers."""

    @staticmethod
    async def create(
        session: AsyncSession,
        name: str,
        type: str,
        base_url: str,
        model: Optional[str] = None,
        config_json: Optional[str] = None,
    ) -> Server:
        """Create a server config."""
        server = Server(
            name=name,
            type=type,
            base_url=base_url,
            model=model,
            config_json=config_json,
        )
        session.add(server)
        await session.flush()
        return server

    @staticmethod
    async def list_all(session: AsyncSession) -> List[Server]:
        """List all servers."""
        result = await session.execute(select(Server).order_by(Server.name))
        return list(result.scalars().all())

    @staticmethod
    async def get_by_name(session: AsyncSession, name: str) -> Optional[Server]:
        """Get server by name."""
        result = await session.execute(
            select(Server).where(Server.name == name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def delete(session: AsyncSession, name: str):
        """Delete server."""
        await session.execute(
            delete(Server).where(Server.name == name)
        )
        await session.flush()

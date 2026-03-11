"""SQLAlchemy ORM models."""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    ForeignKey, Index, TIMESTAMP
)
from sqlalchemy.orm import relationship
from .database import Base


class Benchmark(Base):
    """Benchmark run model."""

    __tablename__ = "benchmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    config_fingerprint = Column(String(64), nullable=False)
    config_yaml = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, index=True)  # pending, running, completed, failed, cancelled
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    started_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    runtime_sec = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON string

    # History tracking
    parent_uuid = Column(String(36), nullable=True, index=True)  # UUID of the parent benchmark (for reruns/edits)
    run_number = Column(Integer, default=1, nullable=False)  # Run number in the history chain

    # Relationships
    scenarios = relationship("BenchmarkScenario", back_populates="benchmark", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_benchmarks_created_at", "created_at"),
        Index("idx_benchmarks_parent_uuid", "parent_uuid"),
    )

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "id": self.id,
            "uuid": self.uuid,
            "name": self.name,
            "description": self.description,
            "config_fingerprint": self.config_fingerprint,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "runtime_sec": self.runtime_sec,
            "error_message": self.error_message,
        }


class BenchmarkScenario(Base):
    """Per-scenario results model."""

    __tablename__ = "benchmark_scenarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False)
    scenario_name = Column(String(255), nullable=False)
    server_name = Column(String(255), nullable=False)

    # Aggregated metrics
    request_count = Column(Integer, nullable=True)
    error_count = Column(Integer, nullable=True)
    p50_ms = Column(Float, nullable=True)
    p90_ms = Column(Float, nullable=True)
    p95_ms = Column(Float, nullable=True)
    p99_ms = Column(Float, nullable=True)
    avg_ms = Column(Float, nullable=True)
    tokens_per_sec_output = Column(Float, nullable=True)
    tokens_per_sec_input = Column(Float, nullable=True)
    tokens_per_sec_total = Column(Float, nullable=True)
    requests_per_sec = Column(Float, nullable=True)
    total_output_tokens = Column(Integer, nullable=True)
    total_input_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    error_rate = Column(Float, nullable=True)

    # TTFB metrics
    ttfb_p50_ms = Column(Float, nullable=True)
    ttfb_p90_ms = Column(Float, nullable=True)
    ttfb_p95_ms = Column(Float, nullable=True)

    # Wait metrics
    wait_p50_ms = Column(Float, nullable=True)
    wait_p95_ms = Column(Float, nullable=True)
    wait_avg_ms = Column(Float, nullable=True)

    # Retry/error metrics
    retries_total = Column(Integer, nullable=True)
    retry_rate = Column(Float, nullable=True)
    error_categories_json = Column(Text, nullable=True)  # JSON string

    # Streaming metrics
    output_tokens_approx_ratio = Column(Float, nullable=True)

    # Relationships
    benchmark = relationship("Benchmark", back_populates="scenarios")
    concurrency_buckets = relationship("BenchmarkConcurrency", back_populates="scenario", cascade="all, delete-orphan")
    requests = relationship("BenchmarkRequest", back_populates="scenario", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_benchmark_scenarios_benchmark_id", "benchmark_id"),
    )

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "id": self.id,
            "scenario_name": self.scenario_name,
            "server_name": self.server_name,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "p50_ms": self.p50_ms,
            "p90_ms": self.p90_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "avg_ms": self.avg_ms,
            "tokens_per_sec_output": self.tokens_per_sec_output,
            "tokens_per_sec_input": self.tokens_per_sec_input,
            "tokens_per_sec_total": self.tokens_per_sec_total,
            "requests_per_sec": self.requests_per_sec,
            "total_output_tokens": self.total_output_tokens,
            "total_input_tokens": self.total_input_tokens,
            "error_rate": self.error_rate,
            "ttfb_p50_ms": self.ttfb_p50_ms,
            "wait_p50_ms": self.wait_p50_ms,
            "retry_rate": self.retry_rate,
        }


class BenchmarkConcurrency(Base):
    """Per-concurrency bucket model."""

    __tablename__ = "benchmark_concurrency"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scenario_id = Column(Integer, ForeignKey("benchmark_scenarios.id", ondelete="CASCADE"), nullable=False)
    concurrency_level = Column(Integer, nullable=False)

    # Metrics (subset of scenario metrics)
    request_count = Column(Integer, nullable=True)
    error_count = Column(Integer, nullable=True)
    p50_ms = Column(Float, nullable=True)
    p95_ms = Column(Float, nullable=True)
    avg_ms = Column(Float, nullable=True)
    tokens_per_sec_output = Column(Float, nullable=True)
    tokens_per_sec_total = Column(Float, nullable=True)
    requests_per_sec = Column(Float, nullable=True)
    error_rate = Column(Float, nullable=True)

    # Relationships
    scenario = relationship("BenchmarkScenario", back_populates="concurrency_buckets")

    __table_args__ = (
        Index("idx_benchmark_concurrency_scenario_id", "scenario_id"),
    )


class BenchmarkRequest(Base):
    """Individual request details model."""

    __tablename__ = "benchmark_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scenario_id = Column(Integer, ForeignKey("benchmark_scenarios.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(String(255), nullable=False)
    start_ts = Column(Float, nullable=False)
    end_ts = Column(Float, nullable=False)
    latency_ms = Column(Float, nullable=False)
    concurrency_level = Column(Integer, nullable=True)

    # Token counts
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    output_tokens_approx = Column(Boolean, default=False)

    # Timing details
    ttfb_ms = Column(Float, nullable=True)
    first_token_gap_ms = Column(Float, nullable=True)
    mean_token_interval_ms = Column(Float, nullable=True)
    token_interval_p95_ms = Column(Float, nullable=True)
    dns_ms = Column(Float, nullable=True)
    connect_ms = Column(Float, nullable=True)
    tls_ms = Column(Float, nullable=True)
    wait_ms = Column(Float, nullable=True)

    # Error tracking
    error = Column(Text, nullable=True)
    error_category = Column(String(50), nullable=True)
    retries = Column(Integer, default=0)

    # Relationships
    scenario = relationship("BenchmarkScenario", back_populates="requests")

    __table_args__ = (
        Index("idx_benchmark_requests_scenario_id", "scenario_id"),
    )


class BenchmarkLog(Base):
    """Benchmark execution logs model."""

    __tablename__ = "benchmark_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    benchmark_id = Column(Integer, ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    level = Column(String(20), nullable=False)  # INFO, WARNING, ERROR, DEBUG
    message = Column(Text, nullable=False)
    source = Column(String(100), nullable=True)  # e.g., "orchestrator", "adapter", "scenario"

    # Relationships
    benchmark = relationship("Benchmark")

    __table_args__ = (
        Index("idx_benchmark_logs_benchmark_id", "benchmark_id"),
        Index("idx_benchmark_logs_timestamp", "timestamp"),
    )


class Server(Base):
    """Saved server configuration model (optional for v1)."""

    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    type = Column(String(50), nullable=False)
    base_url = Column(String(512), nullable=False)
    model = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    config_json = Column(Text, nullable=True)  # Full server config as JSON

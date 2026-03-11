"""Pydantic schemas for API validation and responses."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class BenchmarkCreate(BaseModel):
    """Schema for creating a new benchmark."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    config_yaml: str = Field(..., min_length=1)


class BenchmarkStatus(BaseModel):
    """Lightweight schema for status polling."""
    uuid: str
    status: str
    progress: Optional[int] = None  # 0-100
    current_request_count: Optional[int] = None


class BenchmarkListItem(BaseModel):
    """Lightweight schema for list views."""
    uuid: str
    name: str
    description: Optional[str]
    status: str
    created_at: datetime
    runtime_sec: Optional[float]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class ScenarioResponse(BaseModel):
    """Schema for scenario metrics."""
    scenario_name: str
    server_name: str
    request_count: Optional[int]
    error_count: Optional[int]
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    p99_ms: Optional[float]
    avg_ms: Optional[float]
    tokens_per_sec_output: Optional[float]
    tokens_per_sec_total: Optional[float]
    error_rate: Optional[float]

    class Config:
        from_attributes = True


class BenchmarkResponse(BaseModel):
    """Full benchmark response with all details."""
    uuid: str
    name: str
    description: Optional[str]
    config_fingerprint: str
    status: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    runtime_sec: Optional[float]
    error_message: Optional[str]
    scenarios: List[ScenarioResponse] = []

    class Config:
        from_attributes = True


class ServerCreate(BaseModel):
    """Schema for creating a server config."""
    name: str = Field(..., min_length=1, max_length=255)
    type: str
    base_url: str
    model: Optional[str] = None
    config_json: Optional[str] = None


class ServerResponse(BaseModel):
    """Schema for server response."""
    id: int
    name: str
    type: str
    base_url: str
    model: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

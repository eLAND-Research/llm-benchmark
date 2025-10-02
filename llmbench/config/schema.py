"""Configuration schema definitions using Pydantic v2."""
from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator
import os
import hashlib
import json


class ServerConfig(BaseModel):
    name: str
    type: str = Field(description="Adapter key, e.g. openai_compatible, huggingface_tgi")
    base_url: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    max_retries: int = 3
    timeout_seconds: int = 60
    extra: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_key")
    @classmethod
    def resolve_env(cls, v: Optional[str]):  # type: ignore
        if v and v.startswith("env:"):
            env_key = v.split("env:", 1)[1]
            return os.getenv(env_key) or None
        return v


class ScenarioRequestConfig(BaseModel):
    max_output_tokens: Optional[int] = None
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False


class ScenarioConfig(BaseModel):
    name: str
    type: str
    prompts_file: Optional[str] = None
    runs: int = 1
    concurrency: List[int] = Field(default_factory=lambda: [1])
    request: ScenarioRequestConfig = Field(default_factory=ScenarioRequestConfig)


class PerplexityConfig(BaseModel):
    enabled: bool = False
    dataset: Optional[str] = None


class QAConfig(BaseModel):
    enabled: bool = False
    dataset: Optional[str] = None


class QualityConfig(BaseModel):
    perplexity: PerplexityConfig = Field(default_factory=PerplexityConfig)
    qa_accuracy: QAConfig = Field(default_factory=QAConfig)


class CostModelEntry(BaseModel):
    model_pattern: str
    input_token_usd: float
    output_token_usd: float


class CostModelConfig(BaseModel):
    enabled: bool = False
    entries: List[CostModelEntry] = Field(default_factory=list)


class RemoteMetricsPrometheus(BaseModel):
    name: str
    type: Literal["prometheus"]
    base_url: str
    query: Dict[str, str]
    interval_sec: float = 5.0
    timeout_sec: float = 3.0


class RemoteMetricsJSONHTTP(BaseModel):
    name: str
    type: Literal["json_http"]
    url: str
    method: Literal["GET", "POST"] = "GET"
    headers: Dict[str, str] = Field(default_factory=dict)
    interval_sec: float = 10.0
    parse: Dict[str, str] = Field(default_factory=dict, description="JSONPath or key paths")

    @field_validator("headers")
    @classmethod
    def resolve_header_env(cls, v: Dict[str, str]):  # type: ignore
        resolved = {}
        for k, val in v.items():
            if isinstance(val, str) and val.startswith("Bearer env:"):
                env_key = val.split("env:", 1)[1]
                token = os.getenv(env_key, "")
                resolved[k] = f"Bearer {token}" if token else ""
            elif isinstance(val, str) and val.startswith("env:"):
                env_key = val.split("env:", 1)[1]
                resolved[k] = os.getenv(env_key, "")
            else:
                resolved[k] = val
        return resolved


RemoteMetricsConfig = RemoteMetricsPrometheus | RemoteMetricsJSONHTTP


class RetryPolicyConfig(BaseModel):
    strategy: str = "exponential_backoff"
    base_delay_ms: int = 200
    max_attempts: int = 3


class WarmupConfig(BaseModel):
    requests: int = 0
    discard_metrics: bool = True


class StorageConfig(BaseModel):
    backend: str = "json"
    path: str = "results/latest/raw"


class ReportConfig(BaseModel):
    formats: List[str] = Field(default_factory=lambda: ["markdown", "json"])
    output_dir: str = "results/latest"


class MetricsConfig(BaseModel):
    gpu: Dict[str, Any] = Field(default_factory=dict)
    system: Dict[str, Any] = Field(default_factory=dict)


class RootConfig(BaseModel):
    version: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)
    servers: List[ServerConfig]
    scenarios: List[ScenarioConfig]
    quality: QualityConfig = Field(default_factory=QualityConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    warmup: WarmupConfig = Field(default_factory=WarmupConfig)
    rate_limit: Dict[str, Any] = Field(default_factory=dict)
    retry_policy: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)
    cost_model: CostModelConfig = Field(default_factory=CostModelConfig)
    remote_metrics: List[RemoteMetricsConfig] = Field(default_factory=list)

    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="python"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

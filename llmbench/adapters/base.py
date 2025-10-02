"""Base adapter abstractions for inference servers."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional
import time


@dataclass
class ChatResult:
    model: str
    content: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class StreamingChunk:
    content: str
    is_end: bool = False
    usage: Optional[Dict[str, int]] = None


@dataclass
class EmbeddingResult:
    model: str
    embeddings: List[List[float]]
    usage: Optional[Dict[str, int]] = None
    raw: Optional[Dict[str, Any]] = None


class InferenceAdapter(ABC):
    """Abstract base class for inference API adapters.

    The adapter does NOT handle network-level timing; callers should measure
    DNS/connect/TLS/TTFB externally. Adapter focuses on payload + semantic parsing.
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None, model: Optional[str] = None, **kwargs: Any):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra = kwargs
        self._created_at = time.time()

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **gen_params: Any) -> ChatResult:
        """Perform a non-streaming chat completion."""

    async def chat_stream(self, messages: List[Dict[str, str]], **gen_params: Any) -> AsyncIterator[StreamingChunk]:
        """Optional streaming chat; default raises NotImplementedError."""
        raise NotImplementedError("Streaming not implemented for this adapter")

    @abstractmethod
    async def embeddings(self, inputs: List[str]) -> EmbeddingResult:
        """Fetch embeddings for a batch of input strings."""

    def supports_stream(self) -> bool:  # noqa: D401
        return hasattr(self, "chat_stream") and self.chat_stream.__func__ is not InferenceAdapter.chat_stream  # type: ignore


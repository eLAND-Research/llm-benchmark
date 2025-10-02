"""Mock adapter for local dry-run without real network calls.

Enhanced: supports fail_first_n to simulate transient failures for retry tests."""
from __future__ import annotations
import asyncio
import random
from typing import List, Dict, Any
from .base import InferenceAdapter, ChatResult, EmbeddingResult, StreamingChunk


class MockAdapter(InferenceAdapter):
    def __init__(self, *args, **kwargs):
        self.fail_first_n = int(kwargs.pop("fail_first_n", 0))
        self._failed_calls = 0
        super().__init__(*args, **kwargs)

    async def chat(self, messages: List[Dict[str, str]], **gen_params: Any) -> ChatResult:
        # Simulate transient failure
        if self._failed_calls < self.fail_first_n:
            self._failed_calls += 1
            await asyncio.sleep(0.005)
            raise RuntimeError("simulated transient failure")
        # Simulate variable latency
        await asyncio.sleep(gen_params.get("sleep", 0.01))
        prompt_len = sum(len(m.get("content", "")) for m in messages)
        output_tokens = random.randint(5, 25)
        return ChatResult(
            model=self.model or "mock-model",
            content="<mock-response>",
            input_tokens=prompt_len // 4,
            output_tokens=output_tokens,
            raw={"mock": True},
        )

    async def chat_stream(self, messages: List[Dict[str, str]], **gen_params: Any):  # type: ignore
        # For simplicity streaming path does not simulate failures separately
        for _ in range(3):
            await asyncio.sleep(0.01)
            yield StreamingChunk(content="...", is_end=False)
        yield StreamingChunk(content="", is_end=True)

    async def embeddings(self, inputs: List[str]) -> EmbeddingResult:
        await asyncio.sleep(0.005)
        vecs = [[0.0 for _ in range(8)] for _ in inputs]
        return EmbeddingResult(model=self.model or "mock-model", embeddings=vecs, usage={})

"""OpenAI-compatible adapter (baseline, simplified).

Supports both /chat/completions and /embeddings style endpoints.
Streaming implemented via Server-Sent Events like responses where chunks start with 'data:'.
"""
from __future__ import annotations
import httpx
from typing import List, Dict, Any, AsyncIterator, Optional
from .base import InferenceAdapter, ChatResult, StreamingChunk, EmbeddingResult
import json
import time
import os


class OpenAICompatibleAdapter(InferenceAdapter):
    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def chat(self, messages: List[Dict[str, str]], **gen_params: Any) -> ChatResult:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            **{k: v for k, v in gen_params.items() if v is not None},
            "stream": False,
        }
        start_ts = time.time()
        async with httpx.AsyncClient(timeout=gen_params.get("timeout", 60)) as client:
            try:
                resp = await client.post(url, headers=self._headers(), json=payload)
            except httpx.HTTPError as e:
                raise
            headers_received_ts = time.time()
        if resp.status_code >= 400:
            log_body = os.getenv("LLM_BENCH_LOG_ERROR_BODY", "1") != "0"
            snippet = resp.text[:500] if log_body else "<suppressed>"
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code} error body_snippet={snippet}", request=resp.request, response=resp
            )
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        wait_ms = (headers_received_ts - start_ts) * 1000.0
        data["timings"] = {
            "request_start_ts": start_ts,
            "headers_received_ts": headers_received_ts,
            "wait_ms": wait_ms,
            "dns_ms": None,
            "connect_ms": None,
            "tls_ms": None,
        }
        return ChatResult(
            model=data.get("model", self.model or "unknown"),
            content=content,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=data,
        )

    async def chat_stream(self, messages: List[Dict[str, str]], **gen_params: Any) -> AsyncIterator[StreamingChunk]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            **{k: v for k, v in gen_params.items() if v is not None},
            "stream": True,
        }
        start_ts = time.time()
        first_content_ts: Optional[float] = None
        async with httpx.AsyncClient(timeout=gen_params.get("timeout", 60)) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as r:
                headers_received_ts = time.time()
                if r.status_code >= 400:
                    body = await r.aread()
                    log_body = os.getenv("LLM_BENCH_LOG_ERROR_BODY", "1") != "0"
                    snippet = body.decode(errors="ignore")[:500] if log_body else "<suppressed>"
                    raise httpx.HTTPStatusError(
                        f"HTTP {r.status_code} error body_snippet={snippet}", request=r.request, response=r
                    )
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            timings = {
                                "request_start_ts": start_ts,
                                "headers_received_ts": headers_received_ts,
                                "first_content_ts": first_content_ts,
                                "wait_ms": (headers_received_ts - start_ts) * 1000.0,
                                "ttfb_ms": (first_content_ts - start_ts) * 1000.0 if first_content_ts else None,
                                "dns_ms": None,
                                "connect_ms": None,
                                "tls_ms": None,
                            }
                            yield StreamingChunk(content="", is_end=True, usage={"timings": timings})
                            break
                        try:
                            obj = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        if "content" in delta:
                            if first_content_ts is None:
                                first_content_ts = time.time()
                            yield StreamingChunk(content=delta["content"], is_end=False)
                if first_content_ts is None:
                    first_content_ts = time.time()
                timings = {
                    "request_start_ts": start_ts,
                    "headers_received_ts": headers_received_ts,
                    "first_content_ts": first_content_ts,
                    "wait_ms": (headers_received_ts - start_ts) * 1000.0,
                    "ttfb_ms": (first_content_ts - start_ts) * 1000.0 if first_content_ts else None,
                    "dns_ms": None,
                    "connect_ms": None,
                    "tls_ms": None,
                }
                yield StreamingChunk(content="", is_end=True, usage={"timings": timings})

    async def embeddings(self, inputs: List[str]) -> EmbeddingResult:
        url = f"{self.base_url}/embeddings"
        payload = {"model": self.model, "input": inputs}
        start_ts = time.time()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            headers_received_ts = time.time()
        resp.raise_for_status()
        data = resp.json()
        vectors = [d.get("embedding", []) for d in data.get("data", [])]
        usage = data.get("usage")
        data["timings"] = {
            "request_start_ts": start_ts,
            "headers_received_ts": headers_received_ts,
            "wait_ms": (headers_received_ts - start_ts) * 1000.0,
            "dns_ms": None,
            "connect_ms": None,
            "tls_ms": None,
        }
        return EmbeddingResult(model=data.get("model", self.model or "unknown"), embeddings=vectors, usage=usage, raw=data)

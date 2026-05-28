"""Executor agent -- calls models-under-test and collects LLMResponse objects.

The Executor is a pure Python component (no LLM reasoning required).  It
iterates over every ``(model, benchmark_item)`` pair, sends the prompt via
the OpenAI-compatible chat completions API, and records the response text,
latency, and token count.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List

from openai import AsyncOpenAI, RateLimitError

from llmbench.qual.config import ModelConfig
from llmbench.qual.schemas import BenchmarkDataset, BenchmarkItem, LLMResponse

logger = logging.getLogger(__name__)
_RATE_LIMIT_RETRIES = 2


class Executor:
    """Execute benchmark prompts against one or more models under test.

    Parameters
    ----------
    models:
        List of :class:`ModelConfig` entries representing the models to test.
    """

    def __init__(self, models: list[ModelConfig], max_concurrent: int = 4) -> None:
        self.models = models
        self.max_concurrent = max(1, max_concurrent)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, dataset: BenchmarkDataset) -> List[LLMResponse]:
        """Send every item in *dataset* to every model and collect responses.

        Concurrency is capped at ``self.max_concurrent`` outstanding requests per model via
        ``asyncio.Semaphore``.

        Returns
        -------
        list[LLMResponse]
            One entry per ``(model, item)`` pair.
        """
        all_responses: List[LLMResponse] = []

        for model_cfg in self.models:
            logger.info(
                "Executor: starting model %s (%s) -- %d items",
                model_cfg.name,
                model_cfg.model,
                len(dataset.items),
            )
            client = self._build_client(model_cfg)
            semaphore = asyncio.Semaphore(self.max_concurrent)
            logger.info(
                "Executor: using concurrency=%d for model %s",
                self.max_concurrent,
                model_cfg.name,
            )

            tasks = [
                self._call_model(client, model_cfg, item, semaphore)
                for item in dataset.items
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=False)
            all_responses.extend(responses)

            logger.info(
                "Executor: finished model %s -- %d responses collected",
                model_cfg.name,
                len(responses),
            )

        return all_responses

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_client(model_cfg: ModelConfig) -> AsyncOpenAI:
        """Create an :class:`AsyncOpenAI` client from a :class:`ModelConfig`.

        If ``api_key`` is empty, the client is created with the placeholder
        value ``"not-needed"`` so that the SDK does not raise.
        """
        api_key = model_cfg.api_key if model_cfg.api_key else "not-needed"
        return AsyncOpenAI(
            base_url=model_cfg.base_url,
            api_key=api_key,
            max_retries=0,
        )

    @staticmethod
    async def _call_model(
        client: AsyncOpenAI,
        model_cfg: ModelConfig,
        item: BenchmarkItem,
        semaphore: asyncio.Semaphore,
    ) -> LLMResponse:
        """Send a single prompt to the model and return an :class:`LLMResponse`.

        On failure the ``error`` field is populated and ``response_text`` is
        set to an empty string.
        """
        async with semaphore:
            t0 = time.perf_counter()
            request_messages = [{"role": "user", "content": item.prompt}]
            request_started_at = datetime.now(timezone.utc).isoformat()
            retry_count = 0
            try:
                completion = None
                for attempt in range(_RATE_LIMIT_RETRIES + 1):
                    try:
                        completion = await client.chat.completions.create(
                            model=model_cfg.model,
                            messages=request_messages,
                        )
                        retry_count = attempt
                        break
                    except RateLimitError as exc:
                        retry_count = attempt + 1
                        logger.warning(
                            "Executor: model=%s item=%s rate limited (attempt %d): %s",
                            model_cfg.name,
                            item.id,
                            attempt + 1,
                            exc,
                        )
                        if attempt >= _RATE_LIMIT_RETRIES:
                            raise
                        await asyncio.sleep(_extract_rate_limit_delay(str(exc)))

                if completion is None:
                    raise RuntimeError("Completion request did not return a response.")

                latency_ms = (time.perf_counter() - t0) * 1000.0

                response_text = completion.choices[0].message.content or ""

                # Token count: prefer the API-reported usage; fall back to a
                # rough approximation of 1 token per 4 characters.
                if completion.usage and completion.usage.completion_tokens:
                    token_count = completion.usage.completion_tokens
                else:
                    token_count = len(response_text) // 4

                logger.debug(
                    "Executor: model=%s item=%s latency=%.1fms tokens=%d",
                    model_cfg.name,
                    item.id,
                    latency_ms,
                    token_count,
                )

                return LLMResponse(
                    benchmark_item_id=item.id,
                    model_name=model_cfg.name,
                    response_text=response_text,
                    latency_ms=latency_ms,
                    token_count=token_count,
                    request_messages=request_messages,
                    requested_model=model_cfg.model,
                    requested_at=request_started_at,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count,
                )

            except Exception as exc:  # noqa: BLE001
                latency_ms = (time.perf_counter() - t0) * 1000.0
                logger.warning(
                    "Executor: model=%s item=%s FAILED: %s",
                    model_cfg.name,
                    item.id,
                    exc,
                )
                return LLMResponse(
                    benchmark_item_id=item.id,
                    model_name=model_cfg.name,
                    response_text="",
                    latency_ms=latency_ms,
                    token_count=0,
                    error=str(exc),
                    request_messages=request_messages,
                    requested_model=model_cfg.model,
                    requested_at=request_started_at,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count,
                )


def _extract_rate_limit_delay(error_text: str) -> float:
    """Return a conservative sleep duration for a 429 error."""
    marker = "Limit resets at:"
    if marker in error_text:
        reset_text = error_text.split(marker, 1)[1].strip().rstrip("'").rstrip("}")
        if reset_text.endswith("UTC"):
            reset_text = reset_text[:-3].strip()
        try:
            reset_at = datetime.strptime(reset_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            delay = (reset_at - datetime.now(timezone.utc)).total_seconds() + 1.0
            return max(1.0, min(delay, 30.0))
        except ValueError:
            pass
    return 5.0

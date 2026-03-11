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
from typing import List

from openai import AsyncOpenAI

from llmbench.qual.config import ModelConfig
from llmbench.qual.schemas import BenchmarkDataset, BenchmarkItem, LLMResponse

logger = logging.getLogger(__name__)


class Executor:
    """Execute benchmark prompts against one or more models under test.

    Parameters
    ----------
    models:
        List of :class:`ModelConfig` entries representing the models to test.
    """

    def __init__(self, models: list[ModelConfig]) -> None:
        self.models = models

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, dataset: BenchmarkDataset) -> List[LLMResponse]:
        """Send every item in *dataset* to every model and collect responses.

        Concurrency is capped at 10 outstanding requests per model via
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
            semaphore = asyncio.Semaphore(10)

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
            try:
                completion = await client.chat.completions.create(
                    model=model_cfg.model,
                    messages=[{"role": "user", "content": item.prompt}],
                )
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
                )

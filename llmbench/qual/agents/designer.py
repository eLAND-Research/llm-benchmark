"""Designer agent -- generates BenchmarkDataset from RawMaterials using an LLM.

The Designer takes raw materials collected by the Researcher and uses a strong
LLM (shared with the Judge, configured via ``config.judge.model``) to produce
benchmark items for each configured task type.  For every (task_type, material)
pair the Designer:

1. Renders the *task_prompt* (the prompt that will be sent to models under test)
2. Calls the LLM with the *designer_prompt* to obtain a reference answer and
   a task-specific scoring rubric
3. Parses the JSON response and assembles one or more ``BenchmarkItem`` objects
   (QA tasks may produce multiple items per material)

Concurrency is governed by ``config.judge.max_concurrent`` via an
``asyncio.Semaphore``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Dict, List

from openai import AsyncOpenAI

from llmbench.qual.config import QualConfig
from llmbench.qual.prompts.designer import get_prompts
from llmbench.qual.schemas import (
    BenchmarkDataset,
    BenchmarkItem,
    RawMaterial,
    TaskType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_client(config: QualConfig) -> AsyncOpenAI:
    """Create an ``AsyncOpenAI`` client from the judge model config."""
    model_cfg = config.judge.model
    kwargs: Dict[str, Any] = {"base_url": model_cfg.base_url}
    if model_cfg.api_key:
        kwargs["api_key"] = model_cfg.api_key
    else:
        # openai SDK requires a non-empty string; use a dummy when no key is
        # needed (e.g. local servers).
        kwargs["api_key"] = "no-key"
    return AsyncOpenAI(**kwargs)


def _parse_json_response(text: str) -> Dict[str, Any]:
    """Best-effort extraction of a JSON object from *text*.

    The LLM may wrap the JSON in markdown fences (```json ... ```).  We try
    stripping those before falling back to plain ``json.loads``.
    """
    cleaned = text.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1:]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
        cleaned = cleaned.strip()

    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Designer agent
# ---------------------------------------------------------------------------


class Designer:
    """LLM-powered agent that transforms ``RawMaterial`` into benchmark items.

    Parameters
    ----------
    config:
        The full qual pipeline configuration.  The Designer uses
        ``config.judge.model`` as its backing LLM and
        ``config.judge.max_concurrent`` to limit parallelism.
    """

    def __init__(self, config: QualConfig) -> None:
        self.config = config
        self._client = _build_client(config)
        self._model = config.judge.model.model
        self._semaphore = asyncio.Semaphore(config.judge.max_concurrent)

    # -- public API ---------------------------------------------------------

    async def generate(self, materials: List[RawMaterial]) -> BenchmarkDataset:
        """Generate a :class:`BenchmarkDataset` from a list of raw materials.

        For each task type configured in ``config.task_types``, a random
        sample of ``config.items_per_task`` materials is selected and
        processed concurrently.

        Parameters
        ----------
        materials:
            Raw materials collected by the Researcher agent.

        Returns
        -------
        BenchmarkDataset
            A dataset containing all generated benchmark items.
        """
        task_types: List[str] = self.config.task_types
        items_per_task: int = self.config.items_per_task

        logger.info(
            "Designer: generating benchmark items for %d task types (%s), "
            "%d items per task, from %d materials",
            len(task_types),
            ", ".join(task_types),
            items_per_task,
            len(materials),
        )

        all_items: List[BenchmarkItem] = []
        tasks: List[asyncio.Task[List[BenchmarkItem]]] = []

        for task_type_str in task_types:
            task_type = TaskType(task_type_str)

            # Sample materials (with replacement if we have fewer than needed)
            if len(materials) >= items_per_task:
                sampled = random.sample(materials, items_per_task)
            else:
                logger.warning(
                    "Only %d materials available but %d requested for %s; "
                    "sampling with replacement",
                    len(materials),
                    items_per_task,
                    task_type_str,
                )
                sampled = random.choices(materials, k=items_per_task)

            for material in sampled:
                task = asyncio.create_task(
                    self._generate_item(task_type, material),
                    name=f"designer-{task_type_str}-{material.title[:30]}",
                )
                tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("Designer: task failed with %s: %s", type(result).__name__, result)
                continue
            all_items.extend(result)

        logger.info("Designer: generated %d benchmark items in total", len(all_items))

        resolved_task_types = [TaskType(t) for t in task_types]
        return BenchmarkDataset(
            task_types=resolved_task_types,
            items=all_items,
            metadata={
                "items_per_task": items_per_task,
                "total_materials": len(materials),
            },
        )

    # -- internals ----------------------------------------------------------

    async def _generate_item(
        self,
        task_type: TaskType,
        material: RawMaterial,
    ) -> List[BenchmarkItem]:
        """Call the LLM to produce benchmark item(s) for one material.

        Returns a list because QA tasks produce multiple items (one per QA
        pair).  Other task types return a single-element list.
        """
        prompts = get_prompts(task_type.value)

        # The prompt that will be sent to the models under test
        task_prompt = prompts["task_prompt"].format(
            title=material.title,
            content=material.content,
        )

        # The prompt for the Designer LLM to produce reference answers
        designer_prompt = prompts["designer_prompt"].format(
            title=material.title,
            content=material.content,
        )

        # Default scoring rubric (may be overridden by LLM response)
        default_rubric = prompts["scoring_rubric"]

        async with self._semaphore:
            logger.debug(
                "Designer: calling LLM for task_type=%s, material=%r",
                task_type.value,
                material.title[:50],
            )
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a professional benchmark designer. "
                                "Always respond with valid JSON only, no extra text."
                            ),
                        },
                        {"role": "user", "content": designer_prompt},
                    ],
                    temperature=0.7,
                )
            except Exception:
                logger.exception(
                    "Designer: LLM call failed for task_type=%s, material=%r",
                    task_type.value,
                    material.title[:50],
                )
                raise

        raw_text = response.choices[0].message.content or ""
        logger.debug("Designer: raw LLM response (first 200 chars): %s", raw_text[:200])

        try:
            parsed = _parse_json_response(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "Designer: failed to parse JSON for task_type=%s, material=%r: %s. "
                "Raw response: %s",
                task_type.value,
                material.title[:50],
                exc,
                raw_text[:500],
            )
            # Fallback: use the raw text as-is for reference, default rubric
            return [
                BenchmarkItem(
                    task_type=task_type,
                    source_material=material,
                    prompt=task_prompt,
                    reference_answer=raw_text,
                    scoring_rubric=default_rubric,
                )
            ]

        # Extract scoring rubric (override default if LLM provided one)
        scoring_rubric = parsed.get("scoring_rubric", default_rubric)
        if not isinstance(scoring_rubric, str):
            scoring_rubric = json.dumps(scoring_rubric, ensure_ascii=False)

        # -- QA task: one BenchmarkItem per QA pair -------------------------
        if task_type == TaskType.QA:
            return self._build_qa_items(
                parsed=parsed,
                material=material,
                task_prompt=task_prompt,
                scoring_rubric=scoring_rubric,
                default_rubric=default_rubric,
            )

        # -- All other tasks: single BenchmarkItem --------------------------
        reference_answer = parsed.get("reference_answer", "")
        if not isinstance(reference_answer, str):
            reference_answer = json.dumps(reference_answer, ensure_ascii=False)

        return [
            BenchmarkItem(
                task_type=task_type,
                source_material=material,
                prompt=task_prompt,
                reference_answer=reference_answer,
                scoring_rubric=scoring_rubric,
            )
        ]

    # -- QA-specific helpers ------------------------------------------------

    @staticmethod
    def _build_qa_items(
        *,
        parsed: Dict[str, Any],
        material: RawMaterial,
        task_prompt: str,
        scoring_rubric: str,
        default_rubric: str,
    ) -> List[BenchmarkItem]:
        """Expand a QA designer response into multiple ``BenchmarkItem`` objects.

        The Designer LLM is expected to return::

            {
                "reference_answer": {
                    "qa_pairs": [
                        {"question": "...", "answer": "...", "type": "..."},
                        ...
                    ]
                },
                "scoring_rubric": "..."
            }

        Each QA pair becomes its own ``BenchmarkItem`` whose prompt asks the
        model under test to answer that specific question in context.
        """
        ref = parsed.get("reference_answer", parsed)
        # Handle both {"reference_answer": {"qa_pairs": [...]}} and {"qa_pairs": [...]}
        if isinstance(ref, dict):
            qa_pairs = ref.get("qa_pairs", [])
        else:
            qa_pairs = []

        if not qa_pairs:
            logger.warning(
                "Designer: QA response did not contain qa_pairs, "
                "falling back to single item. Parsed keys: %s",
                list(parsed.keys()),
            )
            return [
                BenchmarkItem(
                    task_type=TaskType.QA,
                    source_material=material,
                    prompt=task_prompt,
                    reference_answer=json.dumps(parsed, ensure_ascii=False),
                    scoring_rubric=scoring_rubric or default_rubric,
                )
            ]

        items: List[BenchmarkItem] = []
        for i, pair in enumerate(qa_pairs):
            question = pair.get("question", "")
            answer = pair.get("answer", "")
            q_type = pair.get("type", "unknown")

            # Build a per-question prompt for the model under test
            per_question_prompt = (
                f"請閱讀以下文章，並回答問題。\n\n"
                f"標題：{material.title}\n\n"
                f"文章內容：\n{material.content}\n\n"
                f"問題：{question}\n\n"
                f"請直接回答，不要加任何前綴或標題。"
            )

            items.append(
                BenchmarkItem(
                    task_type=TaskType.QA,
                    source_material=material,
                    prompt=per_question_prompt,
                    reference_answer=json.dumps(
                        {"question": question, "answer": answer, "type": q_type},
                        ensure_ascii=False,
                    ),
                    scoring_rubric=scoring_rubric or default_rubric,
                )
            )

        logger.debug(
            "Designer: expanded QA response into %d items for material=%r",
            len(items),
            material.title[:50],
        )
        return items

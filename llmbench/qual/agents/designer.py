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
import re
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

_DEFAULT_ASPECT_LABELS = ["人文", "歷史", "政治", "社會", "國際", "科技"]
_ASPECT_KEYWORDS = {
    "人文": ["人文", "文化", "文學", "哲學", "藝術", "宗教", "語言", "博物館", "展覽", "戲劇", "歌仔戲", "表演藝術",
             "族群", "原住民", "客家", "閩南", "民俗", "祭典", "節慶", "傳統", "風俗", "習俗",
             "地理", "地形", "氣候", "河川", "山脈", "景觀", "料理", "飲食", "夜市"],
    "歷史": ["歷史", "古代", "近代", "戰役", "王朝", "年代", "考古", "史料", "史學", "年表", "清朝", "日治", "戰後",
             "殖民", "抗日", "二二八", "戒嚴", "解嚴", "遷台", "開疆", "鄭氏", "荷蘭"],
    "政治": ["政治", "政府", "總統", "立法院", "議會", "選舉", "政黨", "政策", "部會", "公投", "國會", "內閣", "閣揆", "行政院", "縣市長", "外交政策", "朝野",
             "憲法", "法律", "民主", "自由", "三權", "五權", "司法院", "考試院", "監察院"],
    "社會": ["社會", "民生", "醫療", "勞工", "居住", "家庭", "校園", "治安", "司法", "福利", "社福", "長照", "住宅", "房價", "交通", "公安", "食安", "就業", "教育現場",
             "健保", "勞保", "年金", "保險", "少子化", "高齡化", "人口", "生育率", "失業", "薪資",
             "教育", "學校", "課程", "義務教育", "全民健保"],
    "國際": ["國際", "全球", "外交", "聯合國", "美國", "中國", "日本", "歐盟", "俄羅斯", "烏克蘭",
             "兩岸", "中華人民共和國", "北京", "邦交", "台灣海峽", "南海"],
    "科技": ["科技", "技術", "ai", "人工智慧", "晶片", "半導體", "軟體", "網路", "手機", "電腦",
             "台積電", "聯發科", "鴻海", "宏碁", "華碩", "中華電信",
             "晶圓", "積體電路", "製程", "奈米", "5g", "電動車", "太陽能",
             "資訊", "數位", "通訊", "電信", "衛星", "高鐵", "捷運", "科學園區", "工研院", "研發", "再生能源"],
}

# Title-based strong signal (same as api.py _TITLE_ASPECT_MAP)
_TITLE_ASPECT_MAP: dict[str, str] = {
    "台北市": "人文", "高雄市": "人文", "台中市": "人文", "台南市": "人文",
    "新北市": "人文", "桃園市": "人文", "基隆市": "人文", "宜蘭縣": "人文",
    "花蓮縣": "人文", "台東縣": "人文", "澎湖縣": "人文", "金門縣": "人文",
    "馬祖": "人文", "玉山": "人文", "阿里山": "人文", "日月潭": "人文",
    "太魯閣": "人文", "墾丁": "人文", "台灣海峽": "人文",
    "夜市": "人文", "便利商店": "人文", "台灣料理": "人文", "珍珠奶茶": "人文",
    "台灣棒球": "人文", "台灣電影": "人文", "台灣流行音樂": "人文", "台灣文學": "人文",
    "九份": "人文", "台灣鐵路": "人文", "布袋戲": "人文", "歌仔戲": "人文",
    "媽祖": "人文", "台灣民間信仰": "人文", "台灣宗教": "人文", "廟會": "人文", "豐年祭": "人文",
    "臺灣原住民族": "人文", "原住民族": "人文",
    "農曆新年": "人文", "元宵節": "人文", "端午節": "人文", "中元節": "人文", "中秋節": "人文", "清明節": "人文",
    "全民健康保險": "社會", "健康保險": "社會", "少子化": "社會", "高齡化": "社會",
    "長期照護": "社會", "失業保險": "社會", "勞動基準法": "社會", "勞動部": "社會",
    "台灣人口": "社會", "全民教育": "社會", "台灣教育": "社會", "台灣食品安全": "社會",
    "中華民國刑法": "社會", "中華民國民法": "社會", "性別平等": "社會", "同性婚姻": "社會",
    "國民年金": "社會", "衛生福利部": "社會", "教育部": "社會", "內政部": "社會",
    "國民身分證": "社會", "身心障礙": "社會", "國立臺灣大學": "社會", "臺灣大學": "社會",
    "台積電": "科技", "積體電路製造": "科技", "聯華電子": "科技", "聯發科": "科技",
    "鴻海": "科技", "半導體": "科技", "科學工業園區": "科技", "工業技術研究院": "科技",
    "台灣電力": "科技", "高速鐵路": "科技", "人工智慧": "科技", "中華電信": "科技",
    "華碩": "科技", "宏碁": "科技", "再生能源": "科技",
    "中華民國總統": "政治", "行政院": "政治", "立法院": "政治", "憲法": "政治",
    "國慶日": "政治", "司法院": "政治", "國旗": "政治", "總統府": "政治", "外交": "政治",
    "台灣歷史": "歷史", "日治時期": "歷史", "二二八": "歷史", "台灣戒嚴": "歷史",
    "鄭成功": "歷史", "清治時期": "歷史", "荷西": "歷史", "白色恐怖": "歷史", "民主化": "歷史",
    "牡丹社": "歷史", "霧社": "歷史", "遷台": "歷史",
    # 國際
    "中華人民共和國": "國際", "北京市": "國際", "上海市": "國際", "習近平": "國際", "人民幣": "國際",
    "普通話": "國際", "全國人民代表大會": "國際", "國務院": "國際", "中國共產黨": "國際",
    "中華人民共和國國旗": "國際", "中華人民共和國國徽": "國際", "中華人民共和國國慶日": "國際",
    "日本": "國際", "東京都": "國際", "日圓": "國際", "日本國憲法": "國際", "日本天皇": "國際",
    "美國": "國際", "美元": "國際", "華盛頓": "國際", "美國總統": "國際", "美國國會": "國際",
    "大韓民國": "國際", "首爾": "國際",
}


def _split_stance_thread(content: str) -> tuple[str, list[str]]:
    text = (content or "").strip()
    if "【主題】" not in text:
        return text, []

    post_part = text.split("【主題】", 1)[1]
    replies_marker_match = re.search(r"\n\s*【留言(?:（共\s*\d+\s*則）)?】\s*\n", post_part)
    if not replies_marker_match:
        return post_part.strip(), []

    post_text = post_part[:replies_marker_match.start()].strip()
    replies_block = post_part[replies_marker_match.end():].strip()
    if not replies_block:
        return post_text, []

    replies: list[str] = []
    current: list[str] = []
    for line in replies_block.splitlines():
        match = re.match(r"^\s*(\d+)\.\s+(.*\S.*)$", line)
        if match:
            if current:
                replies.append("\n".join(current).strip())
            current = [match.group(2).strip()]
        elif current and line.strip():
            current.append(line.strip())
        elif current and not line.strip():
            current.append("")

    if current:
        replies.append("\n".join(current).strip())

    if not replies and replies_block:
        replies = [replies_block]

    return post_text, [reply for reply in replies if reply.strip()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_client(config: QualConfig) -> AsyncOpenAI:
    """Create an ``AsyncOpenAI`` client from the judge model config."""
    model_cfg = config.judge.model
    kwargs: Dict[str, Any] = {
        "base_url": model_cfg.base_url,
        "max_retries": 0,
    }
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


def _sanitize_qa_question(question: str) -> str:
    clean = (question or "").strip()
    replacements = [
        ("根據文章內容，", ""),
        ("根據文章，", ""),
        ("依據文章內容，", ""),
        ("依據文章，", ""),
        ("根據本文，", ""),
        ("依據本文，", ""),
        ("在文章中，", ""),
        ("在文中，", ""),
        ("文章中", ""),
        ("文中", ""),
        ("本文", ""),
        ("這篇文章", ""),
    ]
    for old, new in replacements:
        clean = clean.replace(old, new)

    clean = re.sub(r"^(根據|依據)(文章內容|文章|本文)[，,、]?\s*", "", clean)
    clean = re.sub(r"^(在)?(文章中|文中)[，,、]?\s*", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" ，,、")
    return clean


def _is_complete_qa_question(question: str) -> bool:
    clean = (question or "").strip()
    if not clean:
        return False

    banned_starts = (
        "主角",
        "上映日期",
        "提到的",
        "這部",
        "這篇",
        "這則",
        "該文",
        "該篇",
        "其",
    )
    if clean.startswith(banned_starts):
        return False

    # Prefer questions with an explicit named subject, typically marked by quotes,
    # book/movie title brackets, company/person/place names, or a leading noun phrase.
    has_explicit_subject = bool(
        re.search(r"[《〈「『].+[》〉」』]", clean)
        or re.search(r"[A-Za-z0-9\u4e00-\u9fff]{2,}(公司|電影|影集|作品|球隊|學校|政府|事件|計畫|政策|平台|品牌|角色|主角)", clean)
        or re.match(r"^[A-Za-z0-9\u4e00-\u9fff]{2,}", clean)
    )
    if not has_explicit_subject:
        return False

    banned_phrases = ("文章中", "文中", "本文", "根據文章", "依據本文", "這篇文章")
    return not any(phrase in clean for phrase in banned_phrases)


def _infer_aspect_from_material(material: RawMaterial) -> str:
    title = (material.title or "").strip()
    # Title map: strong signal, check first
    for pattern, aspect in _TITLE_ASPECT_MAP.items():
        if pattern in title:
            return aspect

    text = " ".join(
        part.strip()
        for part in [title, material.content, material.keyword, material.source_category]
        if part
    ).lower()
    if not text:
        return "社會"

    best_label = "社會"
    best_score = -1
    for label in _DEFAULT_ASPECT_LABELS:
        score = 0
        for keyword in _ASPECT_KEYWORDS.get(label, []):
            key = keyword.lower()
            if key in text:
                score += max(1, text.count(key))
        if label.lower() in text:
            score += 2
        if score > best_score:
            best_score = score
            best_label = label
    return best_label


def _balanced_sample_by_buckets(
    materials: List[RawMaterial],
    items_per_task: int,
    bucket_keys: List[str],
) -> List[RawMaterial]:
    """Generic balanced sampler: sample up to ``items_per_task`` materials,
    keeping representation across the provided ``bucket_keys`` as even as possible.

    ``bucket_keys`` must be a list of strings mapping 1-to-1 with ``materials``
    (i.e. ``bucket_keys[i]`` is the bucket label for ``materials[i]``).
    """
    if len(materials) <= items_per_task:
        return list(materials)

    buckets: dict[str, list[RawMaterial]] = {}
    for material, key in zip(materials, bucket_keys):
        buckets.setdefault(key, []).append(material)

    active_labels = list(buckets.keys())
    if not active_labels:
        return random.sample(materials, items_per_task)

    sampled: list[RawMaterial] = []
    seen_ids: set[int] = set()
    remaining_pool: list[RawMaterial] = []

    base_quota = items_per_task // len(active_labels)
    remainder = items_per_task % len(active_labels)

    for index, label in enumerate(active_labels):
        choices = list(buckets[label])
        quota = base_quota + (1 if index < remainder else 0)
        take = min(len(choices), quota)
        if take <= 0:
            continue
        for material in random.sample(choices, k=take):
            material_id = id(material)
            if material_id in seen_ids:
                continue
            seen_ids.add(material_id)
            sampled.append(material)

        for material in choices:
            if id(material) not in seen_ids:
                remaining_pool.append(material)

    if len(sampled) < items_per_task and remaining_pool:
        sampled.extend(random.sample(remaining_pool, k=min(len(remaining_pool), items_per_task - len(sampled))))

    return sampled[:items_per_task]


def _balanced_sample_materials(materials: List[RawMaterial], items_per_task: int) -> List[RawMaterial]:
    """Sample by inferred aspect (面相) — used for news / social media materials."""
    keys = [_infer_aspect_from_material(m) for m in materials]
    return _balanced_sample_by_buckets(materials, items_per_task, keys)


def _balanced_sample_by_subject(materials: List[RawMaterial], items_per_task: int) -> List[RawMaterial]:
    """Sample by subject (科目) — used for school_qa / exam_bank materials."""
    keys = [m.keyword or "其他" for m in materials]
    return _balanced_sample_by_buckets(materials, items_per_task, keys)


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

            # For school_qa with pre-parsed questions: expand all materials into
            # individual question items first, then sample items_per_task questions
            # from the pool. This prevents one exam PDF (with 30-50 MCQs) from
            # inflating total item count far beyond items_per_task.
            if task_type == TaskType.SCHOOL_QA:
                parsed_materials = [
                    m for m in materials
                    if m.content.startswith("__PARSED_QUESTIONS__\n")
                ]
                if parsed_materials:
                    question_pool: List[BenchmarkItem] = []
                    for m in parsed_materials:
                        question_pool.extend(self._build_items_from_parsed_questions(m))
                    if len(question_pool) > items_per_task:
                        all_items.extend(random.sample(question_pool, items_per_task))
                    else:
                        all_items.extend(question_pool)
                    logger.info(
                        "Designer: school_qa pre-parsed pool=%d, sampled=%d",
                        len(question_pool),
                        min(len(question_pool), items_per_task),
                    )
                    # Handle any non-parsed materials for this task type normally
                    unparsed = [m for m in materials if not m.content.startswith("__PARSED_QUESTIONS__\n")]
                    if not unparsed:
                        continue
                    materials_for_task = unparsed
                else:
                    materials_for_task = materials
            else:
                materials_for_task = materials

            # Sample materials: school_qa balances by subject (科目);
            # all other tasks balance by inferred aspect (面相).
            if len(materials_for_task) >= items_per_task:
                if task_type == TaskType.SCHOOL_QA:
                    sampled = _balanced_sample_by_subject(materials_for_task, items_per_task)
                else:
                    sampled = _balanced_sample_materials(materials_for_task, items_per_task)
            else:
                logger.warning(
                    "Only %d materials available but %d requested for %s; "
                    "sampling with replacement",
                    len(materials_for_task),
                    items_per_task,
                    task_type_str,
                )
                if not materials_for_task:
                    raise ValueError(
                        "No materials collected from data source. "
                        "Check your search config and API key."
                    )
                sampled = random.choices(materials_for_task, k=items_per_task)

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
        # -- Pre-parsed questions bypass (exam_bank with parse_questions=True) --
        # Content starts with __PARSED_QUESTIONS__\n<JSON> — skip LLM entirely.
        if task_type == TaskType.SCHOOL_QA and material.content.startswith("__PARSED_QUESTIONS__\n"):
            return self._build_items_from_parsed_questions(material)

        # Skip materials with insufficient content (avoids "please paste the text" responses)
        if len(material.content.strip()) < 20:
            logger.warning(
                "Designer: skipping material with insufficient content (len=%d): %r",
                len(material.content.strip()),
                material.title[:50],
            )
            return []

        # For stance_analysis: require minimum content length for meaningful analysis
        if task_type == TaskType.STANCE_ANALYSIS:
            content = material.content.strip()
            if len(content) < 50:
                logger.info(
                    "Designer: skipping stance_analysis material — too short (len=%d): %r",
                    len(content), material.title[:50],
                )
                return []

            thread_post, replies = _split_stance_thread(material.content)
            if len(replies) > 1:
                logger.info(
                    "Designer: splitting stance thread %r into %d reply-level tasks",
                    material.title[:50],
                    len(replies),
                )
                split_tasks: List[asyncio.Task[List[BenchmarkItem]]] = []
                for idx, reply_text in enumerate(replies, start=1):
                    split_material = material.model_copy(update={
                        "title": f"{material.title}｜留言{idx}",
                        "content": f"【主題】\n{thread_post}\n\n【留言（共 1 則）】\n{reply_text}",
                    })
                    split_tasks.append(
                        asyncio.create_task(
                            self._generate_item(task_type, split_material),
                            name=f"designer-{task_type.value}-{material.title[:20]}-reply-{idx}",
                        )
                    )

                split_items: List[BenchmarkItem] = []
                split_results = await asyncio.gather(*split_tasks, return_exceptions=True)
                for idx, result in enumerate(split_results, start=1):
                    if isinstance(result, Exception):
                        logger.error(
                            "Designer: reply-level stance task failed for %r reply %d with %s: %s",
                            material.title[:50],
                            idx,
                            type(result).__name__,
                            result,
                        )
                        continue
                    split_items.extend(result)
                return split_items

        prompts = get_prompts(task_type.value)

        # The prompt that will be sent to the models under test
        task_prompt = prompts["task_prompt"].format(
            title=material.title,
            content=material.content,
        )

        # Cross-country confusion test: use a different designer prompt when
        # the source material is about a foreign country.
        n_questions = getattr(self.config, "questions_per_article", 10)
        if task_type == TaskType.TRUE_FALSE and material.source_category == "國外知識":
            from llmbench.qual.prompts.designer import CROSS_COUNTRY_TRUE_FALSE_DESIGNER_PROMPT
            designer_prompt = CROSS_COUNTRY_TRUE_FALSE_DESIGNER_PROMPT.format(
                title=material.title,
                content=material.content,
                n_questions=n_questions,
            )
        else:
            designer_prompt = prompts["designer_prompt"].format(
                title=material.title,
                content=material.content,
                n_questions=n_questions,
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
                    temperature=0,
                    max_completion_tokens=700,
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

        # -- School QA task: one BenchmarkItem per question -----------------
        if task_type == TaskType.SCHOOL_QA:
            return self._build_school_qa_items(
                parsed=parsed,
                material=material,
                scoring_rubric=scoring_rubric,
                default_rubric=default_rubric,
            )

        # -- True/False task: one BenchmarkItem per statement ----------------
        if task_type == TaskType.TRUE_FALSE:
            return self._build_true_false_items(
                parsed=parsed,
                material=material,
                scoring_rubric=scoring_rubric,
                default_rubric=default_rubric,
            )


        # -- QA task: one BenchmarkItem per QA pair -------------------------
        if task_type == TaskType.QA:
            return self._build_qa_items(
                parsed=parsed,
                material=material,
                task_prompt=task_prompt,
                scoring_rubric=scoring_rubric,
                default_rubric=default_rubric,
            )

        # -- Stance analysis: normalize reference_answer and embed topic ----
        if task_type == TaskType.STANCE_ANALYSIS:
            def _normalize_stance_topic(raw_topic: str) -> str:
                topic = (raw_topic or "").strip()
                if not topic:
                    return ""
                replacements = [
                    ("作者對", ""),
                    ("作者將", ""),
                    ("作者", ""),
                    ("其", ""),
                    ("看法", ""),
                    ("想法", ""),
                    ("態度", ""),
                    ("立場", ""),
                    ("觀點", ""),
                    ("正面", ""),
                    ("負面", ""),
                    ("讚賞", ""),
                    ("批評", ""),
                    ("支持", ""),
                    ("反對", ""),
                ]
                for old, new in replacements:
                    topic = topic.replace(old, new)
                topic = " ".join(topic.split())
                topic = topic.strip("，。；：、 ")
                return topic

            topic = _normalize_stance_topic(parsed.get("topic", ""))
            raw_ref = parsed.get("reference_answer", {})
            # LLM sometimes nests the full outer dict inside reference_answer
            if isinstance(raw_ref, dict) and "reference_answer" in raw_ref:
                inner = raw_ref["reference_answer"]
                if not topic:
                    topic = raw_ref.get("topic", "")
                # Pull scoring_rubric from the nested wrapper if not already set
                if not parsed.get("scoring_rubric") and raw_ref.get("scoring_rubric"):
                    scoring_rubric = raw_ref["scoring_rubric"]
                    if not isinstance(scoring_rubric, str):
                        scoring_rubric = json.dumps(scoring_rubric, ensure_ascii=False)
                raw_ref = inner
            # Normalize to {topic, stance, evidence}
            if isinstance(raw_ref, dict):
                normalized_ref = {
                    "topic": _normalize_stance_topic(raw_ref.get("topic", topic)),
                    "stance": raw_ref.get("stance", ""),
                    "evidence": raw_ref.get("evidence", ""),
                }
            else:
                normalized_ref = {"topic": topic, "stance": "", "evidence": str(raw_ref)}
            if topic:
                scoring_rubric = f"【主題描述】{topic}\n\n{scoring_rubric}"
            reference_answer = json.dumps(normalized_ref, ensure_ascii=False)
        else:
            # -- All other tasks: single BenchmarkItem ----------------------
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
            question = _sanitize_qa_question(pair.get("question", ""))
            answer = pair.get("answer", "")
            q_type = pair.get("type", "unknown")
            if not _is_complete_qa_question(question):
                logger.warning(
                    "Designer: dropping incomplete QA question for material=%r: %r",
                    material.title[:50],
                    question,
                )
                continue

            # QA items are intended to test the model's direct answer recall
            # without exposing the source article at inference time.
            per_question_prompt = question

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

    # -- School QA-specific helpers -----------------------------------------

    @staticmethod
    def _build_school_qa_items(
        *,
        parsed: Dict[str, Any],
        material: RawMaterial,
        scoring_rubric: str,
        default_rubric: str,
    ) -> List[BenchmarkItem]:
        """Expand a school_qa designer response into BenchmarkItem objects.

        The Designer LLM is expected to return::

            {
                "questions": [
                    {
                        "type": "選擇題",
                        "question": "...",
                        "choices": {"A": ..., "B": ..., "C": ..., "D": ...},
                        "answer": "A",
                        "explanation": "..."
                    },
                    {
                        "type": "填充題",
                        "question": "含 ___ 的句子",
                        "answer": "答案",
                        "explanation": "..."
                    },
                    {
                        "type": "問答題",
                        "question": "...",
                        "answer": "參考答案",
                        "explanation": "..."
                    }
                ],
                "scoring_rubric": "..."
            }

        Each question becomes its own ``BenchmarkItem``.
        """
        questions = parsed.get("questions", [])
        if not questions:
            logger.warning(
                "Designer: school_qa response did not contain 'questions', "
                "falling back to single item. Parsed keys: %s",
                list(parsed.keys()),
            )
            return [
                BenchmarkItem(
                    task_type=TaskType.SCHOOL_QA,
                    source_material=material,
                    prompt=json.dumps(parsed, ensure_ascii=False),
                    reference_answer=json.dumps(parsed, ensure_ascii=False),
                    scoring_rubric=scoring_rubric or default_rubric,
                )
            ]

        items: List[BenchmarkItem] = []
        for q in questions:
            q_type = q.get("type", "問答題")
            question_text = (q.get("question") or "").strip()
            answer = q.get("answer", "")
            explanation = q.get("explanation", "")

            if not question_text:
                logger.warning(
                    "Designer: skipping school_qa question with empty text for material=%r",
                    material.title[:50],
                )
                continue

            # Build the task prompt for the model under test
            if q_type == "選擇題":
                choices = q.get("choices", {})
                norm_answer = str(answer or "").strip().upper()
                if not norm_answer or norm_answer not in "ABCD":
                    logger.warning(
                        "Designer: skipping school_qa 選擇題 with missing answer for material=%r",
                        material.title[:50],
                    )
                    continue
                answer = norm_answer
                choices_text = "\n".join(
                    f"{k}. {v}" for k, v in sorted(choices.items()) if v
                )
                prompt = (
                    f"以下是一道選擇題，請選出正確答案（只需回答選項代號 A/B/C/D）。\n\n"
                    f"{question_text}\n{choices_text}"
                )
                reference = json.dumps(
                    {"type": q_type, "question": question_text,
                     "choices": choices, "answer": answer, "explanation": explanation},
                    ensure_ascii=False,
                )
            elif q_type == "填充題":
                prompt = f"以下是一道填充題，請填入 ___ 中缺少的詞語（只需回答填入的詞語）。\n\n{question_text}"
                reference = json.dumps(
                    {"type": q_type, "question": question_text,
                     "answer": answer, "explanation": explanation},
                    ensure_ascii=False,
                )
            else:  # 問答題 or unknown
                prompt = f"請回答以下問題（用 1 至 3 句話作答）。\n\n{question_text}"
                reference = json.dumps(
                    {"type": q_type, "question": question_text,
                     "answer": answer, "explanation": explanation},
                    ensure_ascii=False,
                )

            items.append(
                BenchmarkItem(
                    task_type=TaskType.SCHOOL_QA,
                    source_material=material,
                    prompt=prompt,
                    reference_answer=reference,
                    scoring_rubric=scoring_rubric or default_rubric,
                )
            )

        logger.debug(
            "Designer: expanded school_qa response into %d items for material=%r",
            len(items),
            material.title[:50],
        )
        return items

    # -- Pre-parsed questions (no LLM) --------------------------------------

    @staticmethod
    def _build_items_from_parsed_questions(material: RawMaterial) -> List[BenchmarkItem]:
        """Build BenchmarkItems directly from pre-parsed MCQ questions.

        Used when ``exam_bank`` source is run with ``parse_questions=True``.
        The content format is::

            __PARSED_QUESTIONS__
            [{"number": 11, "question": "...", "choices": {...}, "answer": "B"}, ...]

        No LLM call is made — each question becomes one BenchmarkItem immediately.
        """
        from llmbench.qual.prompts.designer import SCHOOL_QA_SCORING_RUBRIC

        raw_json = material.content.split("\n", 1)[1]
        try:
            questions = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.error(
                "Designer: failed to decode pre-parsed questions for %r: %s",
                material.title[:50], exc,
            )
            return []

        items: List[BenchmarkItem] = []
        for q in questions:
            q_num = q.get("number", "")
            stem = (q.get("question") or "").strip()
            choices: dict = q.get("choices", {})
            answer = str(q.get("answer") or "").strip().upper()
            if not stem or len(choices) < 3:
                continue
            if not answer or answer not in "ABCD":
                logger.debug(
                    "Designer: skipping pre-parsed question %r — missing or invalid answer %r",
                    stem[:50], answer,
                )
                continue

            choices_text = "\n".join(f"{k}. {v}" for k, v in sorted(choices.items()))
            prompt = (
                f"以下是一道選擇題，請選出正確答案（只需回答選項代號）。\n\n"
                f"{stem}\n{choices_text}"
            )
            reference = json.dumps(
                {"type": "選擇題", "number": q_num,
                 "question": stem, "choices": choices, "answer": answer},
                ensure_ascii=False,
            )
            items.append(BenchmarkItem(
                task_type=TaskType.SCHOOL_QA,
                source_material=material,
                prompt=prompt,
                reference_answer=reference,
                scoring_rubric=SCHOOL_QA_SCORING_RUBRIC,
            ))

        logger.debug(
            "Designer: built %d items from pre-parsed questions for %r",
            len(items), material.title[:50],
        )
        return items

    # -- True/False builder --------------------------------------------------

    @staticmethod
    def _build_true_false_items(
        *,
        parsed: Dict[str, Any],
        material: RawMaterial,
        scoring_rubric: str,
        default_rubric: str,
    ) -> List[BenchmarkItem]:
        from llmbench.qual.prompts.designer import TRUE_FALSE_SCORING_RUBRIC

        questions = parsed.get("questions", [])
        if not questions:
            logger.warning("Designer: true_false response had no questions for %r", material.title[:50])
            return []

        items: List[BenchmarkItem] = []
        for q in questions:
            statement = (q.get("statement") or "").strip()
            answer = str(q.get("answer") or "").strip().upper()
            explanation = (q.get("explanation") or "").strip()

            if not statement or answer not in ("TRUE", "FALSE"):
                logger.debug("Designer: skipping true_false item with invalid answer %r", answer)
                continue

            prompt = f"以下關於台灣的陳述，是否為正確的台灣事實？\n請只回答 TRUE（正確）或 FALSE（錯誤），不要有其他文字。\n\n{statement}"
            reference = json.dumps(
                {"statement": statement, "answer": answer, "explanation": explanation},
                ensure_ascii=False,
            )
            items.append(BenchmarkItem(
                task_type=TaskType.TRUE_FALSE,
                source_material=material,
                prompt=prompt,
                reference_answer=reference,
                scoring_rubric=scoring_rubric or TRUE_FALSE_SCORING_RUBRIC,
            ))

        return items

"""Taiwan knowledge source — fetches articles from Chinese Wikipedia.

Returns RawMaterial objects suitable for the true_false pipeline.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .schemas import RawMaterial

logger = logging.getLogger(__name__)

# Wikipedia categories → article titles to seed from
_DEFAULT_TITLES: List[str] = [
    # 政治 / 制度
    "中華民國總統", "中華民國行政院", "中華民國立法院", "中華民國司法院",
    "中華民國憲法", "中華民國國慶日", "中華民國國旗",
    # 地理
    "台灣", "台北市", "高雄市", "台中市", "台南市", "新北市",
    "台北101", "阿里山", "玉山", "日月潭", "太魯閣國家公園",
    # 文化 / 生活
    "台灣夜市", "台灣便利商店", "台灣料理", "台灣原住民族",
    "台灣正體中文",
    # 歷史
    "台灣歷史", "台灣日治時期", "二二八事件", "台灣戒嚴",
    "中華民國政府遷台",
    # 教育 / 社會
    "台灣教育", "台灣大學學科能力測驗", "台灣義務教育",
]

_WIKI_API = "https://zh.wikipedia.org/w/api.php"


def load_taiwan_knowledge_materials(
    titles: Optional[List[str]] = None,
    max_chars: int = 3000,
    timeout: int = 20,
    batch_size: int = 10,
) -> List[RawMaterial]:
    """Fetch Wikipedia articles in batches and return as RawMaterial list."""
    import urllib.request
    import urllib.parse
    import json
    import time
    from datetime import datetime

    target_titles = titles if titles else _DEFAULT_TITLES
    materials: List[RawMaterial] = []
    now_ym = datetime.now().strftime("%Y%m")
    month_range = {"start": now_ym, "end": now_ym}

    # Batch titles to reduce API calls and avoid 429
    for i in range(0, len(target_titles), batch_size):
        batch = target_titles[i:i + batch_size]
        try:
            params = urllib.parse.urlencode({
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "redirects": 1,
                "titles": "|".join(batch),
                "format": "json",
                "utf8": 1,
            })
            url = f"{_WIKI_API}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "llmbench/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                if page.get("pageid", -1) < 0:
                    logger.debug("taiwan_knowledge: page not found: %s", page.get("title"))
                    continue
                text = (page.get("extract") or "").strip()
                if not text or len(text) < 100:
                    logger.debug("taiwan_knowledge: too short, skipping: %s", page.get("title"))
                    continue
                text = text[:max_chars]
                materials.append(RawMaterial(
                    title=page.get("title", ""),
                    content=text,
                    source_category="台灣知識",
                    keyword=page.get("title", ""),
                    month_range=month_range,
                ))
                logger.info("taiwan_knowledge: loaded %d chars for %r", len(text), page.get("title"))

        except Exception as exc:
            logger.warning("taiwan_knowledge: batch fetch failed: %s", exc)

        if i + batch_size < len(target_titles):
            time.sleep(1)  # avoid rate limiting

    logger.info("taiwan_knowledge: %d materials loaded", len(materials))
    return materials

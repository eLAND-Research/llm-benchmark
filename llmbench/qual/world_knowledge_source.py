"""World knowledge source — fetches non-Taiwan country articles from Wikipedia.

Returns RawMaterial objects with source_category="國外知識" for use in
cross-country confusion tests (true_false pipeline).  The materials serve as
distractor context so the Designer can generate FALSE statements that confuse
Taiwan facts with foreign country facts (e.g. "台灣的貨幣是人民幣").
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .schemas import RawMaterial

logger = logging.getLogger(__name__)

# Primary focus: China/PRC (main confusion source) + a few other countries
_DEFAULT_TITLES: List[str] = [
    # 中華人民共和國（主要混淆來源）
    "中華人民共和國",
    "北京市",
    "上海市",
    "人民幣",
    "習近平",
    "普通話",
    "中華人民共和國國慶日",
    "中華人民共和國國旗",
    "中華人民共和國國徽",
    "中華人民共和國國務院",
    "全國人民代表大會",
    "中國共產黨",
    # 日本
    "日本",
    "東京都",
    "日圓",
    "日本國憲法",
    "日本天皇",
    # 美國
    "美國",
    "美元",
    "華盛頓哥倫比亞特區",
    "美國總統",
    "美國國會",
    # 大韓民國
    "大韓民國",
    "首爾特別市",
]

_WIKI_API = "https://zh.wikipedia.org/w/api.php"


def load_world_knowledge_materials(
    titles: Optional[List[str]] = None,
    max_chars: int = 3000,
    timeout: int = 20,
    batch_size: int = 10,
) -> List[RawMaterial]:
    """Fetch Wikipedia articles about non-Taiwan countries and return as RawMaterial list.

    Parameters
    ----------
    titles:
        Article titles to fetch.  Defaults to a curated list focused on
        China/PRC (the primary confusion source) plus other major countries.
    max_chars:
        Maximum characters to keep per article (default 3000).
    timeout:
        HTTP request timeout in seconds.
    batch_size:
        Number of titles to fetch per API call.
    """
    import json
    import time
    import urllib.parse
    import urllib.request
    from datetime import datetime

    target_titles = titles if titles else _DEFAULT_TITLES
    materials: List[RawMaterial] = []
    now_ym = datetime.now().strftime("%Y%m")
    month_range = {"start": now_ym, "end": now_ym}

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
                    logger.debug("world_knowledge: page not found: %s", page.get("title"))
                    continue
                text = (page.get("extract") or "").strip()
                if not text or len(text) < 100:
                    logger.debug("world_knowledge: too short, skipping: %s", page.get("title"))
                    continue
                text = text[:max_chars]
                materials.append(RawMaterial(
                    title=page.get("title", ""),
                    content=text,
                    source_category="國外知識",
                    keyword=page.get("title", ""),
                    month_range=month_range,
                ))
                logger.info("world_knowledge: loaded %d chars for %r", len(text), page.get("title"))

        except Exception as exc:
            logger.warning("world_knowledge: batch fetch failed: %s", exc)

        if i + batch_size < len(target_titles):
            time.sleep(1)

    logger.info("world_knowledge: %d materials loaded", len(materials))
    return materials

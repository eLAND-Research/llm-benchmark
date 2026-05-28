"""Taiwan.md knowledge base data source for the qual pipeline.

Fetches articles from the open-source Taiwan.md repository on GitHub
(https://github.com/frank890417/taiwan-md) and converts them to
RawMaterial objects.

License: Content is CC BY-SA 4.0. Attribution required.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

import requests

from llmbench.qual.schemas import RawMaterial

logger = logging.getLogger(__name__)

_BASE_URL = "https://raw.githubusercontent.com/frank890417/taiwan-md/master/knowledge"
_TRANSLATIONS_URL = f"{_BASE_URL}/_translations.json"
_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "taiwan_md_cache"
_TRANSLATIONS_CACHE = _CACHE_DIR / "_translations.json"

_ALL_CATEGORIES = [
    "About", "Art", "Culture", "Economy", "Food",
    "Geography", "History", "Lifestyle", "Music",
    "Nature", "People", "Society", "Technology",
]


def _strip_markdown_metadata(text: str) -> str:
    """Remove YAML frontmatter and clean up markdown for use as plain text."""
    text = re.sub(r"^---[\s\S]*?---\n?", "", text.strip())
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _title_from_path(path: str) -> str:
    """Extract a human-readable title from a file path."""
    filename = path.split("/")[-1].replace(".md", "")
    return filename.replace("-", " ").replace("_", " ")


def _cache_path_for_article(path: str) -> Path:
    return _CACHE_DIR.joinpath(*path.split("/"))


def _read_text_if_exists(path: Path) -> Optional[str]:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _write_cache(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fetch_text(url: str, timeout: int) -> str:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _fetch_json(url: str, timeout: int) -> dict:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _load_translations(timeout: int, refresh: bool) -> dict:
    if not refresh and _TRANSLATIONS_CACHE.exists():
        return json.loads(_TRANSLATIONS_CACHE.read_text(encoding="utf-8"))

    try:
        translations = _fetch_json(_TRANSLATIONS_URL, timeout=timeout)
        _write_cache(_TRANSLATIONS_CACHE, json.dumps(translations, ensure_ascii=False, indent=2))
        return translations
    except Exception as exc:
        if _TRANSLATIONS_CACHE.exists():
            logger.warning("Taiwan.md: failed to refresh translations, falling back to cache: %s", exc)
            return json.loads(_TRANSLATIONS_CACHE.read_text(encoding="utf-8"))
        raise ConnectionError(f"Failed to fetch Taiwan.md index: {exc}") from exc


def _load_article(path: str, timeout: int, refresh: bool) -> Optional[str]:
    cache_path = _cache_path_for_article(path)
    if not refresh:
        cached = _read_text_if_exists(cache_path)
        if cached is not None:
            return cached

    url = f"{_BASE_URL}/{path}"
    try:
        raw_content = _fetch_text(url, timeout=timeout)
        _write_cache(cache_path, raw_content)
        return raw_content
    except Exception as exc:
        cached = _read_text_if_exists(cache_path)
        if cached is not None:
            logger.warning("Taiwan.md: failed to refresh %s, falling back to cache: %s", path, exc)
            return cached
        logger.warning("Taiwan.md: failed to fetch %s: %s", path, exc)
        return None


def prefetch_taiwan_md_cache(
    categories: Optional[List[str]] = None,
    lang: str = "zh-TW",
    limit: Optional[int] = None,
    timeout: int = 15,
) -> int:
    """Download Taiwan.md source files into the local cache.

    Returns the number of cached articles.
    """
    load_taiwan_md_materials(
        categories=categories,
        lang=lang,
        limit=limit,
        timeout=timeout,
        refresh=True,
    )
    return sum(1 for _ in _CACHE_DIR.rglob("*.md"))


def load_taiwan_md_materials(
    categories: Optional[List[str]] = None,
    lang: str = "zh-TW",
    limit: Optional[int] = None,
    timeout: int = 15,
    refresh: bool = False,
) -> List[RawMaterial]:
    """Load articles from Taiwan.md, using a local cache when available."""
    target_categories = [c.strip() for c in (categories or _ALL_CATEGORIES)]

    logger.info(
        "Taiwan.md: loading articles (lang=%s, categories=%s, limit=%s, refresh=%s)",
        lang, target_categories, limit, refresh,
    )

    translations = _load_translations(timeout=timeout, refresh=refresh)

    paths: list[tuple[str, str]] = []
    if lang == "zh-TW":
        for _, zh_path in translations.items():
            if not isinstance(zh_path, str):
                continue
            parts = zh_path.split("/")
            if len(parts) >= 2:
                category = parts[0]
                if category in target_categories:
                    paths.append((zh_path, category))
    else:
        for en_path in translations.keys():
            parts = en_path.replace("en/", "").split("/")
            if len(parts) >= 2:
                category = parts[0]
                if category in target_categories:
                    paths.append((en_path, category))

    logger.info("Taiwan.md: found %d article paths", len(paths))

    materials: List[RawMaterial] = []
    for path, category in paths:
        if limit and len(materials) >= limit:
            break

        raw_content = _load_article(path, timeout=timeout, refresh=refresh)
        if raw_content is None:
            continue

        content = _strip_markdown_metadata(raw_content)
        if len(content) < 50:
            logger.debug("Taiwan.md: skipping short article %s", path)
            continue

        materials.append(RawMaterial(
            source_category=f"taiwan_md/{category}",
            title=_title_from_path(path),
            content=content,
            keyword=category,
            month_range={"start": "", "end": ""},
        ))

    logger.info("Taiwan.md: loaded %d articles", len(materials))
    return materials

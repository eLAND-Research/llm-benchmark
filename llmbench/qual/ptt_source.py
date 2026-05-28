"""PTT board data source for the qual pipeline.

Fetches articles from public PTT boards and converts them into RawMaterial
objects for challenge generation.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from llmbench.qual.schemas import RawMaterial

logger = logging.getLogger(__name__)

_PTT_BASE_URL = "https://www.ptt.cc"
_INDEX_PATH = "/bbs/{board}/index.html"
_PTT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
_ARTICLE_RE = re.compile(r"/bbs/(?P<board>[^/]+)/(?P<article_id>M\.\d+\.[A-Z0-9]+\.[A-Z0-9]+)\.html")
_MONTH_MAP = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_DEFAULT_EXCLUDED_TITLE_PREFIXES = ("re:", "fw:", "[公告]", "公告")


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _sanitize_text(text: str) -> str:
    text = unescape(text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _make_title(text: str, max_len: int = 60) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return first_line[:max_len] if first_line else text[:max_len]


def _parse_ptt_date(date_text: str) -> Optional[datetime]:
    raw = _collapse_whitespace(date_text)
    if not raw:
        return None

    parts = raw.split()
    if len(parts) < 5:
        return None

    month = _MONTH_MAP.get(parts[1])
    if not month:
        return None

    try:
        day = int(parts[2])
        hh, mm, ss = [int(v) for v in parts[3].split(":")]
        year = int(parts[4])
        return datetime(year, month, day, hh, mm, ss)
    except Exception:
        return None


def _datetime_to_month(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y%m") if dt else ""


def _datetime_to_date(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y%m%d") if dt else ""


def _ptt_push_score(push_tag: str) -> int:
    tag = (push_tag or "").strip()
    if tag.startswith("推"):
        return 1
    if tag.startswith("噓"):
        return -1
    return 0


def _format_thread(content: str, pushes: list[str]) -> str:
    parts = [f"【主題】\n{content.strip()}"]
    clean_pushes = [p.strip() for p in pushes if p and p.strip()]
    if clean_pushes:
        push_lines = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(clean_pushes))
        parts.append(f"【留言（共 {len(clean_pushes)} 則）】\n{push_lines}")
    return "\n\n".join(parts)


def _is_excluded_title(title: str, exclude_title_prefixes: Optional[list[str]] = None) -> bool:
    normalized = (title or "").strip().lower()
    prefixes = exclude_title_prefixes or list(_DEFAULT_EXCLUDED_TITLE_PREFIXES)
    return any(normalized.startswith(prefix.strip().lower()) for prefix in prefixes if prefix.strip())


@dataclass
class PTTArticleSummary:
    article_id: str
    title: str
    url: str
    push_count: int = 0


@dataclass
class PTTPush:
    tag: str
    user: str
    content: str


@dataclass
class PTTArticle:
    article_id: str
    board: str
    title: str
    author: str
    posted_at: Optional[datetime]
    content: str
    pushes: list[PTTPush]
    url: str


@dataclass
class PTTLoadReport:
    pages_requested: int
    pages_loaded: int = 0
    index_entries_seen: int = 0
    articles_loaded: int = 0
    skipped_duplicate: int = 0
    skipped_min_push_count: int = 0
    skipped_title_prefix: int = 0
    skipped_title_contains: int = 0
    skipped_empty_content: int = 0
    skipped_date_start: int = 0
    skipped_date_end: int = 0
    skipped_min_text_length: int = 0
    skipped_text_contains: int = 0
    fetch_failures: int = 0
    output_materials: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "pages_requested": self.pages_requested,
            "pages_loaded": self.pages_loaded,
            "index_entries_seen": self.index_entries_seen,
            "articles_loaded": self.articles_loaded,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_min_push_count": self.skipped_min_push_count,
            "skipped_title_prefix": self.skipped_title_prefix,
            "skipped_title_contains": self.skipped_title_contains,
            "skipped_empty_content": self.skipped_empty_content,
            "skipped_date_start": self.skipped_date_start,
            "skipped_date_end": self.skipped_date_end,
            "skipped_min_text_length": self.skipped_min_text_length,
            "skipped_text_contains": self.skipped_text_contains,
            "fetch_failures": self.fetch_failures,
            "output_materials": self.output_materials,
        }


class _BoardIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[PTTArticleSummary] = []
        self._in_entry = False
        self._entry_div_depth = 0
        self._in_title_div = False
        self._title_div_depth = 0
        self._current_href: Optional[str] = None
        self._current_title_parts: list[str] = []
        self._capture_title = False
        self._current_push_parts: list[str] = []
        self._capture_push = False
        self._push_div_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_map = dict(attrs)
        class_name = attrs_map.get("class", "") or ""
        if tag == "div" and "r-ent" in class_name.split():
            self._in_entry = True
            self._entry_div_depth = 1
            self._in_title_div = False
            self._title_div_depth = 0
            self._current_href = None
            self._current_title_parts = []
            self._current_push_parts = []
            self._capture_push = False
            self._push_div_depth = 0
            return
        elif self._in_entry and tag == "div":
            self._entry_div_depth += 1
            if "title" in class_name.split():
                self._in_title_div = True
                self._title_div_depth = 1
            elif self._in_title_div:
                self._title_div_depth += 1
            if "nrec" in class_name.split():
                self._capture_push = True
                self._push_div_depth = 1
            elif self._capture_push:
                self._push_div_depth += 1
        elif self._in_entry and self._in_title_div and tag == "a":
            href = attrs_map.get("href")
            if href and _ARTICLE_RE.search(href):
                self._current_href = href
                self._capture_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_title = False
        elif tag == "div" and self._in_entry:
            if self._in_title_div:
                self._title_div_depth -= 1
                if self._title_div_depth <= 0:
                    self._in_title_div = False
                    self._title_div_depth = 0

            if self._capture_push:
                self._push_div_depth -= 1
                if self._push_div_depth <= 0:
                    self._capture_push = False
                    self._push_div_depth = 0

            self._entry_div_depth -= 1
            if self._entry_div_depth <= 0:
                self._finalize_entry()
                self._in_entry = False
                self._entry_div_depth = 0

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._current_title_parts.append(data)
        elif self._capture_push:
            self._current_push_parts.append(data)

    def _finalize_entry(self) -> None:
        if not self._current_href:
            return
        match = _ARTICLE_RE.search(self._current_href)
        if not match:
            return
        title = _collapse_whitespace("".join(self._current_title_parts))
        if not title:
            return
        push_count = _parse_push_count("".join(self._current_push_parts))
        self.entries.append(
            PTTArticleSummary(
                article_id=match.group("article_id"),
                title=title,
                url=urljoin(_PTT_BASE_URL, self._current_href),
                push_count=push_count,
            )
        )


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta_values: list[str] = []
        self._capture_meta_value = False
        self._skip_depth = 0
        self._body_parts: list[str] = []
        self.pushes: list[PTTPush] = []
        self._in_push = False
        self._capture_push_tag = False
        self._capture_push_user = False
        self._capture_push_content = False
        self._push_tag_parts: list[str] = []
        self._push_user_parts: list[str] = []
        self._push_content_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_map = dict(attrs)
        class_name = attrs_map.get("class", "") or ""
        classes = class_name.split()

        if tag == "span" and "article-meta-value" in classes:
            self._capture_meta_value = True
            return

        if tag == "div" and "push" in classes:
            self._in_push = True
            self._push_tag_parts = []
            self._push_user_parts = []
            self._push_content_parts = []
            return

        if self._in_push and tag == "span":
            if "push-tag" in classes:
                self._capture_push_tag = True
            elif "push-userid" in classes:
                self._capture_push_user = True
            elif "push-content" in classes:
                self._capture_push_content = True
            return

        if tag in {"script", "style"}:
            self._skip_depth += 1
            return

        if self._skip_depth == 0 and not self._in_push:
            if tag == "br":
                self._body_parts.append("\n")
            elif tag == "p":
                self._body_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._capture_meta_value = False
            self._capture_push_tag = False
            self._capture_push_user = False
            self._capture_push_content = False
            return

        if tag == "div" and self._in_push:
            self._finalize_push()
            self._in_push = False
            return

        if tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture_meta_value:
            self.meta_values.append(data)
            return
        if self._capture_push_tag:
            self._push_tag_parts.append(data)
            return
        if self._capture_push_user:
            self._push_user_parts.append(data)
            return
        if self._capture_push_content:
            self._push_content_parts.append(data)
            return
        if self._skip_depth == 0 and not self._in_push:
            self._body_parts.append(data)

    def _finalize_push(self) -> None:
        tag = _collapse_whitespace("".join(self._push_tag_parts))
        user = _collapse_whitespace("".join(self._push_user_parts))
        content = _collapse_whitespace("".join(self._push_content_parts)).lstrip(":").strip()
        if content:
            self.pushes.append(PTTPush(tag=tag, user=user, content=content))

    @property
    def raw_content(self) -> str:
        return "".join(self._body_parts)


def _parse_push_count(raw: str) -> int:
    text = _collapse_whitespace(raw)
    if not text:
        return 0
    if text == "爆":
        return 100
    if text.startswith("X") and text[1:].isdigit():
        return -int(text[1:])
    try:
        return int(text)
    except Exception:
        return 0


def _strip_article_body(raw_html_text: str) -> str:
    text = _sanitize_text(raw_html_text)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("※ 發信站: 批踢踢實業坊"):
            break
        if stripped.startswith("--"):
            break
        if stripped in {"看板 Movie", "作者", "標題", "時間"}:
            continue
        lines.append(line.rstrip())
    return _sanitize_text("\n".join(lines))


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(_PTT_HEADERS)
    session.cookies.set("over18", "1", domain="www.ptt.cc")
    return session


def _fetch_text(url: str, timeout: int) -> str:
    session = _build_session()
    last_error: Exception | None = None
    try:
        for attempt in range(1, 4):
            try:
                resp = session.get(
                    url,
                    timeout=timeout,
                    headers={"Referer": _PTT_BASE_URL + "/bbs/movie/index.html"},
                )
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("PTT fetch failed (attempt %d/3) for %s: %s", attempt, url, exc)
                if attempt >= 3:
                    break
                time.sleep(1.5 * attempt)
    finally:
        session.close()

    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch PTT URL: {url}")


def _load_index_page(board: str, page_url: Optional[str], timeout: int) -> tuple[list[PTTArticleSummary], Optional[str]]:
    url = page_url or urljoin(_PTT_BASE_URL, _INDEX_PATH.format(board=board))
    html = _fetch_text(url, timeout=timeout)
    parser = _BoardIndexParser()
    parser.feed(html)
    prev_match = re.search(
        r'<a class="btn wide" href="([^"]+index\d+\.html)">\s*(?:&lsaquo;|‹)\s*上頁',
        html,
    )
    prev_url = urljoin(_PTT_BASE_URL, prev_match.group(1)) if prev_match else None
    return parser.entries, prev_url


def _load_article(summary: PTTArticleSummary, timeout: int) -> PTTArticle:
    html = _fetch_text(summary.url, timeout=timeout)
    parser = _ArticleParser()
    parser.feed(html)

    meta = [_collapse_whitespace(v) for v in parser.meta_values]
    author = meta[0] if len(meta) > 0 else ""
    title = meta[2] if len(meta) > 2 else summary.title
    posted_at = _parse_ptt_date(meta[3]) if len(meta) > 3 else None
    content = _strip_article_body(parser.raw_content)

    article_match = _ARTICLE_RE.search(summary.url)
    board = article_match.group("board") if article_match else ""

    return PTTArticle(
        article_id=summary.article_id,
        board=board,
        title=title or summary.title,
        author=author,
        posted_at=posted_at,
        content=content,
        pushes=parser.pushes,
        url=summary.url,
    )


def load_ptt_board_materials(
    board: str = "movie",
    pages: int = 1,
    keyword: str = "",
    title_contains: Optional[str] = None,
    text_contains: Optional[str] = None,
    min_push_count: int = 0,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    combine_pushes: bool = True,
    include_pushes: bool = False,
    max_pushes_per_article: Optional[int] = 10,
    min_text_length: int = 0,
    exclude_title_prefixes: Optional[list[str]] = None,
    limit: Optional[int] = None,
    timeout: int = 15,
    return_report: bool = False,
) -> List[RawMaterial] | tuple[List[RawMaterial], PTTLoadReport]:
    """Load articles from a PTT board as RawMaterial objects."""
    board = (board or "movie").strip().lower()
    if pages < 1:
        raise ValueError("pages must be >= 1")

    title_contains_lower = title_contains.lower() if title_contains else None
    text_contains_lower = text_contains.lower() if text_contains else None
    materials: List[RawMaterial] = []
    seen_ids: set[str] = set()
    current_page: Optional[str] = None
    report = PTTLoadReport(pages_requested=pages)

    for _ in range(pages):
        try:
            entries, current_page = _load_index_page(board=board, page_url=current_page, timeout=timeout)
        except requests.RequestException as exc:
            report.fetch_failures += 1
            logger.warning("Skipping PTT index page due to fetch error: %s", exc)
            break
        if not entries:
            break
        report.pages_loaded += 1
        report.index_entries_seen += len(entries)

        for entry in entries:
            if limit and len(materials) >= limit:
                report.output_materials = len(materials)
                logger.info("Loaded %d PTT materials from board=%s", len(materials), board)
                return (materials, report) if return_report else materials
            if entry.article_id in seen_ids:
                report.skipped_duplicate += 1
                continue
            if entry.push_count < min_push_count:
                report.skipped_min_push_count += 1
                continue
            if _is_excluded_title(entry.title, exclude_title_prefixes):
                report.skipped_title_prefix += 1
                continue
            if title_contains_lower and title_contains_lower not in entry.title.lower():
                report.skipped_title_contains += 1
                continue

            try:
                article = _load_article(entry, timeout=timeout)
            except requests.RequestException as exc:
                report.fetch_failures += 1
                logger.warning("Skipping PTT article %s due to fetch error: %s", entry.url, exc)
                continue
            report.articles_loaded += 1
            if not article.content:
                report.skipped_empty_content += 1
                continue

            article_date = _datetime_to_date(article.posted_at)
            if date_start and article_date and article_date < date_start:
                report.skipped_date_start += 1
                continue
            if date_end and article_date and article_date > date_end:
                report.skipped_date_end += 1
                continue
            if min_text_length and len(article.content) < min_text_length:
                report.skipped_min_text_length += 1
                continue
            if text_contains_lower and text_contains_lower not in article.content.lower():
                report.skipped_text_contains += 1
                continue

            seen_ids.add(entry.article_id)
            month = _datetime_to_month(article.posted_at)
            pushes_text = [f"{push.tag} {push.content}".strip() for push in article.pushes if push.content]
            if max_pushes_per_article and max_pushes_per_article > 0:
                pushes_text = pushes_text[:max_pushes_per_article]

            if combine_pushes:
                materials.append(
                    RawMaterial(
                        source_category=f"ptt/{board}",
                        title=article.title or _make_title(article.content),
                        content=_format_thread(article.content, pushes_text),
                        keyword=keyword or board,
                        month_range={"start": month, "end": month},
                    )
                )
            else:
                materials.append(
                    RawMaterial(
                        source_category=f"ptt/{board}",
                        title=article.title or _make_title(article.content),
                        content=article.content,
                        keyword=keyword or board,
                        month_range={"start": month, "end": month},
                    )
                )

            if include_pushes and not combine_pushes:
                push_iter = article.pushes[:max_pushes_per_article] if max_pushes_per_article and max_pushes_per_article > 0 else article.pushes
                for idx, push in enumerate(push_iter, 1):
                    if not push.content:
                        continue
                    if limit and len(materials) >= limit:
                        report.output_materials = len(materials)
                        logger.info("Loaded %d PTT materials from board=%s", len(materials), board)
                        return (materials, report) if return_report else materials
                    materials.append(
                        RawMaterial(
                            source_category=f"ptt/{board}_push",
                            title=f"{article.title} / push {idx}",
                            content=f"{push.tag} {push.content}".strip(),
                            keyword=keyword or board,
                            month_range={"start": month, "end": month},
                        )
                    )

        if not current_page:
            break

    report.output_materials = len(materials)
    logger.info("Loaded %d PTT materials from board=%s", len(materials), board)
    return (materials, report) if return_report else materials

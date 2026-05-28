"""Threads scraper data source for the qual pipeline.

Reads local JSON files produced by the threads-scraper project and converts
posts (and optionally their replies) into :class:`~llmbench.qual.schemas.RawMaterial`
objects for use in the qual pipeline.

Expected file format (one JSON array per file)::

    [
      {
        "id": "...",
        "text": "post content",
        "timestamp": 1770965969,
        "username": "alice",
        "like_count": 42,
        "replies_count": 3,
        "repost_count": 5,
        "permalink": "https://www.threads.com/...",
        "replies": [
          {
            "id": "...",
            "text": "reply content",
            "timestamp": 1770966000,
            "username": "bob",
            "like_count": 1
          }
        ]
      }
    ]
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Matches common emoji Unicode blocks (covers most Emoji 15 characters).
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FFFF"   # Mahjong/domino/misc symbols/emoticons/transport/etc.
    "\U00002600-\U000027BF"   # Misc symbols, Dingbats
    "\U0000FE00-\U0000FE0F"   # Variation selectors
    "\U00002300-\U000023FF"   # Misc technical
    "\U00002B00-\U00002BFF"   # Misc symbols/arrows
    "\u200d"                  # Zero-width joiner
    "\uFE0F"                  # Variation selector-16
    "]+",
    re.UNICODE,
)


def _is_emoji_only(text: str) -> bool:
    """Return True if *text* contains nothing but emojis and whitespace."""
    return not _EMOJI_RE.sub("", text).strip()

from llmbench.qual.schemas import RawMaterial

logger = logging.getLogger(__name__)


def _timestamp_to_month(ts: int) -> str:
    """Convert a Unix timestamp to YYYYMM string."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y%m")


def _make_title(text: str, max_len: int = 60) -> str:
    """Use the first line (or first max_len chars) of text as a title."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return first_line[:max_len] if first_line else text[:max_len]


def _timestamp_to_date(ts: int) -> str:
    """Convert a Unix timestamp to YYYYMMDD string."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y%m%d")


def _format_thread(post_text: str, replies: list, post_username: str = "") -> str:
    """Format a post and replies from other users as a structured thread.

    Returns a string with 【主題】 and 【留言】 sections.
    Self-replies from the original author are excluded.
    """
    parts = [f"【主題】\n{post_text.strip()}"]
    author = (post_username or "").strip().lower()
    valid_replies = []
    for reply in replies:
        reply_text = reply.get("text", "").strip()
        reply_username = (reply.get("username", "") or "").strip().lower()
        if not reply_text:
            continue
        if author and reply_username and reply_username == author:
            continue
        valid_replies.append(reply_text)
    if valid_replies:
        reply_lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(valid_replies))
        parts.append(f"【留言（共 {len(valid_replies)} 則）】\n{reply_lines}")
    return "\n\n".join(parts)

def load_threads_materials(
    directory: str | Path,
    keyword: str = "",
    include_replies: bool = False,
    combine_replies: bool = False,
    min_like_count: int = 0,
    min_replies_count: int = 0,
    min_repost_count: int = 0,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    text_contains: Optional[str] = None,
    min_text_length: int = 0,
    exclude_emoji_only: bool = False,
    limit: Optional[int] = None,
) -> List[RawMaterial]:
    """Load Threads posts from a directory of JSON files as RawMaterial objects.

    Parameters
    ----------
    directory:
        Path to the directory containing ``*.json`` scraper output files.
    keyword:
        Keyword label to attach to each RawMaterial (used for tracking only,
        not for filtering).
    include_replies:
        If True, also include reply texts as separate RawMaterial items.
    combine_replies:
        If True, combine the post and all its replies into a single RawMaterial
        with a structured 【主題】/【留言】 format. Overrides include_replies.
    min_like_count:
        Skip posts with fewer likes than this threshold.
    min_replies_count:
        Skip posts with fewer replies than this threshold.
    min_repost_count:
        Skip posts with fewer reposts than this threshold.
    date_start:
        Only include posts on or after this date (YYYYMMDD).
    date_end:
        Only include posts on or before this date (YYYYMMDD).
    text_contains:
        Only include posts whose text contains this substring (case-insensitive).
    min_text_length:
        Skip posts whose text is shorter than this number of characters.
    limit:
        Maximum total number of RawMaterial objects to return.

    Returns
    -------
    List[RawMaterial]
        Deduplicated list of raw materials.
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Threads data directory not found: {directory}")

    json_files = sorted(directory.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No JSON files found in: {directory}")

    logger.info(
        "Loading Threads data from %s (%d files)", directory, len(json_files)
    )

    text_contains_lower = text_contains.lower() if text_contains else None

    seen_ids: set[str] = set()
    materials: List[RawMaterial] = []

    for filepath in json_files:
        try:
            with filepath.open("r", encoding="utf-8") as f:
                posts = json.load(f)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", filepath.name, exc)
            continue

        for post in posts:
            if limit and len(materials) >= limit:
                break

            post_id = post.get("id", "")
            text = post.get("text", "").strip()
            post_username = post.get("username", "")
            timestamp = post.get("timestamp", 0)
            like_count = post.get("like_count") or 0
            replies_count = post.get("replies_count") or 0
            repost_count = post.get("repost_count") or 0

            if not text:
                continue
            if like_count < min_like_count:
                continue
            if replies_count < min_replies_count:
                continue
            if repost_count < min_repost_count:
                continue
            if min_text_length and len(text) < min_text_length:
                continue
            if text_contains_lower and text_contains_lower not in text.lower():
                continue
            if exclude_emoji_only and _is_emoji_only(text):
                continue
            if timestamp and (date_start or date_end):
                post_date = _timestamp_to_date(timestamp)
                if date_start and post_date < date_start:
                    continue
                if date_end and post_date > date_end:
                    continue
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            month = _timestamp_to_month(timestamp) if timestamp else ""
            raw_replies = post.get("replies", [])

            if combine_replies:
                # Combine post + replies into one structured RawMaterial
                content = _format_thread(text, raw_replies, post_username=post_username)
                materials.append(RawMaterial(
                    source_category="threads",
                    title=_make_title(text),
                    content=content,
                    keyword=keyword,
                    month_range={"start": month, "end": month},
                ))
            else:
                materials.append(RawMaterial(
                    source_category="threads",
                    title=_make_title(text),
                    content=text,
                    keyword=keyword,
                    month_range={"start": month, "end": month},
                ))

            if not combine_replies and include_replies:
                for reply in post.get("replies", []):
                    if limit and len(materials) >= limit:
                        break
                    reply_id = reply.get("id", "")
                    reply_text = reply.get("text", "").strip()
                    reply_ts = reply.get("timestamp", timestamp)

                    if not reply_text or reply_id in seen_ids:
                        continue
                    seen_ids.add(reply_id)

                    reply_month = _timestamp_to_month(reply_ts) if reply_ts else month
                    materials.append(RawMaterial(
                        source_category="threads_reply",
                        title=_make_title(reply_text),
                        content=reply_text,
                        keyword=keyword,
                        month_range={"start": reply_month, "end": reply_month},
                    ))

        if limit and len(materials) >= limit:
            break

    logger.info("Loaded %d Threads materials (%d unique)", len(materials), len(seen_ids))
    return materials

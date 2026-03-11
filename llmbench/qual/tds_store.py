"""
TDS incremental data store.

Architecture:
  Layer 1 - tds_fetch_log   : daily fetch status (skip if already done)
  Layer 2 - tds_articles    : raw article snapshots per day
  Layer 3 - tds_topic_days  : LLM-computed topic aggregations per day
  Layer 4 - tds_analysis_cache : trend analysis result cache (keyed by date window)

Daily workflow:
  store = TDSStore()
  store.backfill(days=30)          # fetch any missing days (idempotent)
  store.compute_missing_topics()   # run LLM on un-processed days
  result = store.get_trend(days=14) # fast: reads from SQLite, no TDS call
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TDS_URL = "http://10.20.30.1:6060/web/P2PServer.jsp"
LITELLM_URL = "https://llmgw.elandai.cloud/v1/chat/completions"
LITELLM_API_KEY = "sk-MpF28Nob8sv4ZnD2DwYuVA"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_DB = Path(__file__).parent.parent.parent / "llmbench.db"

# articles per day to store (profile says ≤100 is fast)
ARTICLES_PER_DAY = 100

# LLM topics per day
TOPICS_PER_DAY = 15

# analysis cache TTL in hours
CACHE_TTL_HOURS = 6


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS tds_fetch_log (
    date        TEXT PRIMARY KEY,   -- "2026-03-01"
    fetched_at  TEXT NOT NULL,
    article_count INTEGER DEFAULT 0,
    total_count   INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'ok'   -- ok | no_data | error
);

CREATE TABLE IF NOT EXISTS tds_articles (
    article_id   TEXT NOT NULL,
    date         TEXT NOT NULL,
    content      TEXT,
    comment_count INTEGER DEFAULT 0,
    post_time    TEXT,
    fetched_at   TEXT,
    PRIMARY KEY (article_id, date)
);
CREATE INDEX IF NOT EXISTS idx_tds_articles_date ON tds_articles(date);

CREATE TABLE IF NOT EXISTS tds_topic_days (
    date         TEXT NOT NULL,
    topic        TEXT NOT NULL,
    total_comments INTEGER DEFAULT 0,
    article_count  INTEGER DEFAULT 0,
    summary      TEXT,
    computed_at  TEXT,
    PRIMARY KEY (date, topic)
);
CREATE INDEX IF NOT EXISTS idx_tds_topic_days_date ON tds_topic_days(date);
CREATE INDEX IF NOT EXISTS idx_tds_topic_days_topic ON tds_topic_days(topic);

CREATE TABLE IF NOT EXISTS tds_analysis_cache (
    cache_key    TEXT PRIMARY KEY,  -- sha256 of (start_date, end_date, analysis_type)
    computed_at  TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    result_json  TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# TDS raw query
# ---------------------------------------------------------------------------

def _tds_fetch_day(date: datetime, max_record: int = ARTICLES_PER_DAY) -> Dict[str, Any]:
    ym = date.strftime("%y%m")
    start_dt = date.strftime("%Y/%m/%d 00:00:00.000")
    end_dt = date.strftime("%Y/%m/%d 23:59:59.999")

    query = {
        "version": "0.5 sync",
        "query_type": "keyword",
        "keyword": "",
        "field_filter": {"expr": {"and": {"expr_string": "POST_TIME&CONTENT_TYPE",
            "field_map": {
                "POST_TIME": {"post_time": f"{start_dt}~{end_dt}"},
                "CONTENT_TYPE": {"content_type": "1;"},
            }}}},
        "target_db": [f"WH_News_1%20{ym}%", f"WH_News_2%20{ym}%"],
        "search_mode": {"search_mode": "normal", "homophone": False,
                        "homograph": False, "chinese_convert": False,
                        "form_convert": False, "field_weight_sort": False},
        "search_order": [{"field": "comment_count", "order_type": "des"}],
        "search_range": {"start_pos": 0, "max_record": max_record},
        "result_field": ["id", "content", "comment_count", "post_time"],
    }

    body = urllib.parse.urlencode({
        "action": "search",
        "txtInput_json": json.dumps(query, ensure_ascii=False),
    }).encode("utf-8")

    req = urllib.request.Request(
        TDS_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# LiteLLM helper
# ---------------------------------------------------------------------------

def _llm_chat(messages: List[Dict], max_tokens: int = 2000) -> str:
    payload = json.dumps({
        "model": DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        LITELLM_URL, data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {LITELLM_API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# TDSStore
# ---------------------------------------------------------------------------

class TDSStore:
    """Incremental TDS data store backed by SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DEFAULT_DB)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(DDL)

    # ------------------------------------------------------------------ #
    # Layer 1+2: fetch & store raw articles
    # ------------------------------------------------------------------ #

    def is_fetched(self, date: datetime) -> bool:
        key = date.strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM tds_fetch_log WHERE date=?", (key,)
            ).fetchone()
        return row is not None and row["status"] in ("ok", "no_data")

    def fetch_day(self, date: datetime, force: bool = False, quiet: bool = False) -> int:
        """
        Fetch and store articles for a single day.
        Returns article_count stored. Skips if already fetched (unless force=True).
        """
        key = date.strftime("%Y-%m-%d")

        if not force and self.is_fetched(date):
            if not quiet:
                print(f"  ⏭  {key} 已有快取，跳過")
            return 0

        try:
            data = _tds_fetch_day(date)
            items = data.get("result_list") or []
            total = int((data.get("response_list") or {}).get("total_count", 0) or 0)
            now = datetime.now().isoformat()

            with self._conn() as conn:
                # fetch log
                conn.execute(
                    "INSERT OR REPLACE INTO tds_fetch_log VALUES (?,?,?,?,?)",
                    (key, now, len(items), total, "ok" if items else "no_data"),
                )
                # articles
                for item in items:
                    content = re.sub(r"<[^>]+>", "", item.get("content", ""))[:300]
                    conn.execute(
                        "INSERT OR IGNORE INTO tds_articles VALUES (?,?,?,?,?,?)",
                        (
                            item.get("id", ""),
                            key,
                            content,
                            int(item.get("comment_count", 0) or 0),
                            item.get("post_time", ""),
                            now,
                        ),
                    )

            if not quiet:
                print(f"  ✓  {key}  {len(items):3d} 篇  (資料庫共 {total:,} 筆)")
            return len(items)

        except Exception as e:
            key2 = date.strftime("%Y-%m-%d")
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tds_fetch_log VALUES (?,?,?,?,?)",
                    (key2, datetime.now().isoformat(), 0, 0, f"error:{e}"),
                )
            if not quiet:
                print(f"  ✗  {key}  錯誤: {e}")
            return 0

    def backfill(self, days: int = 30, delay_ms: int = 300) -> None:
        """
        Fetch any missing days in the past N days.
        Skips already-fetched days automatically.
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        missing = [
            today - timedelta(days=i)
            for i in range(1, days + 1)
            if not self.is_fetched(today - timedelta(days=i))
        ]

        if not missing:
            print(f"  ✅ 過去 {days} 天資料全部已快取")
            return

        print(f"\n  📥 補抓 {len(missing)} 天資料（共 {days} 天範圍）")
        for d in missing:
            self.fetch_day(d)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)

    # ------------------------------------------------------------------ #
    # Layer 3: LLM topic computation per day
    # ------------------------------------------------------------------ #

    def _topics_computed(self, date: datetime) -> bool:
        key = date.strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tds_topic_days WHERE date=? LIMIT 1", (key,)
            ).fetchone()
        return row is not None

    def compute_day_topics(self, date: datetime, force: bool = False) -> List[Dict]:
        """
        Use LLM to group a day's articles into topics.
        Stores results in tds_topic_days. Idempotent.
        """
        key = date.strftime("%Y-%m-%d")

        if not force and self._topics_computed(date):
            return self._load_day_topics(key)

        # load articles for this day
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT content, comment_count FROM tds_articles WHERE date=? ORDER BY comment_count DESC",
                (key,),
            ).fetchall()

        if not rows:
            return []

        lines = "\n".join(
            f"留言:{r['comment_count']} | {r['content'][:80]}"
            for r in rows
        )

        raw = _llm_chat([
            {
                "role": "system",
                "content": (
                    f"今天是 {key}。根據以下新聞（含留言數），"
                    f"將相似新聞歸納成最多 {TOPICS_PER_DAY} 個主題，"
                    "計算每個主題的總留言數和文章數。\n"
                    "主題名稱要精簡（5字內），且保持一致性（同類事件用同名）。\n"
                    '回傳 JSON: {"topics": [{"topic": "名稱", "total_comments": 數字, '
                    '"article_count": 數字, "summary": "20字摘要"}]}'
                ),
            },
            {"role": "user", "content": lines},
        ])

        topics = json.loads(raw).get("topics", [])
        now = datetime.now().isoformat()

        with self._conn() as conn:
            conn.execute("DELETE FROM tds_topic_days WHERE date=?", (key,))
            conn.executemany(
                "INSERT INTO tds_topic_days VALUES (?,?,?,?,?,?)",
                [
                    (key, t["topic"], t.get("total_comments", 0),
                     t.get("article_count", 0), t.get("summary", ""), now)
                    for t in topics
                ],
            )

        return topics

    def _load_day_topics(self, date_key: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tds_topic_days WHERE date=? ORDER BY total_comments DESC",
                (date_key,),
            ).fetchall()
        return [dict(r) for r in rows]

    def compute_missing_topics(self, days: int = 30) -> None:
        """Compute topics for all fetched-but-unprocessed days."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        dates = [today - timedelta(days=i) for i in range(1, days + 1)]
        pending = [d for d in dates if self.is_fetched(d) and not self._topics_computed(d)]

        if not pending:
            print(f"  ✅ 過去 {days} 天主題全部已計算")
            return

        print(f"\n  🤖 計算 {len(pending)} 天的主題分析")
        for d in pending:
            key = d.strftime("%Y-%m-%d")
            topics = self.compute_day_topics(d)
            top = topics[0]["topic"] if topics else "無資料"
            print(f"  ✓  {key}  {len(topics)} 個主題  (最熱: {top})")

    # ------------------------------------------------------------------ #
    # Layer 4: trend analysis from pre-computed data
    # ------------------------------------------------------------------ #

    def get_topic_timeseries(self, days: int = 30) -> Dict[str, List[Dict]]:
        """
        Build per-topic time series from tds_topic_days.
        Returns: {"topic_name": [{"date": "...", "comments": N, "articles": N}, ...]}
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_key = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        with self._conn() as conn:
            rows = conn.execute(
                """SELECT date, topic, total_comments, article_count
                   FROM tds_topic_days WHERE date >= ?
                   ORDER BY date, total_comments DESC""",
                (start_key,),
            ).fetchall()

        series: Dict[str, List[Dict]] = {}
        for r in rows:
            series.setdefault(r["topic"], []).append({
                "date": r["date"],
                "comments": r["total_comments"],
                "articles": r["article_count"],
            })
        return series

    def get_trend(
        self,
        days: int = 14,
        top_n: int = 10,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Compute rising/cooling topics from pre-computed daily data.
        Fast: reads only from SQLite, no TDS or LLM calls.

        Trend score = (recent_half_avg - early_half_avg) / (early_half_avg + 1)
        """
        cache_key = hashlib.sha256(f"trend:{days}:{top_n}".encode()).hexdigest()[:16]

        # check cache
        if use_cache:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT result_json, expires_at FROM tds_analysis_cache WHERE cache_key=?",
                    (cache_key,),
                ).fetchone()
            if row and row["expires_at"] > datetime.now().isoformat():
                return json.loads(row["result_json"])

        series = self.get_topic_timeseries(days=days)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        all_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days, 0, -1)]
        mid = len(all_dates) // 2
        early_dates = set(all_dates[:mid])
        recent_dates = set(all_dates[mid:])

        scored = []
        for topic, points in series.items():
            by_date = {p["date"]: p["comments"] for p in points}
            early_vals = [by_date.get(d, 0) for d in early_dates]
            recent_vals = [by_date.get(d, 0) for d in recent_dates]
            early_avg = sum(early_vals) / len(early_vals)
            recent_avg = sum(recent_vals) / len(recent_vals)
            total = sum(v for v in by_date.values())
            score = (recent_avg - early_avg) / (early_avg + 1)
            active_days = len([v for v in by_date.values() if v > 0])

            scored.append({
                "topic": topic,
                "score": score,
                "early_avg": round(early_avg),
                "recent_avg": round(recent_avg),
                "total_comments": total,
                "active_days": active_days,
                "daily": [{"date": d, "comments": by_date.get(d, 0)} for d in all_dates],
            })

        # filter: must appear in at least 2 days
        scored = [s for s in scored if s["active_days"] >= 2]
        scored.sort(key=lambda x: x["score"], reverse=True)

        rising = scored[:top_n]
        cooling = sorted(scored, key=lambda x: x["score"])[:top_n]
        cooling = [c for c in cooling if c["score"] < -0.2]

        result = {
            "rising": rising,
            "cooling": cooling,
            "computed_at": datetime.now().isoformat(),
            "days": days,
            "date_range": {
                "start": all_dates[0],
                "end": all_dates[-1],
            },
        }

        # cache
        expires = (datetime.now() + timedelta(hours=CACHE_TTL_HOURS)).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tds_analysis_cache VALUES (?,?,?,?)",
                (cache_key, datetime.now().isoformat(), expires, json.dumps(result)),
            )

        return result

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self, days: int = 30) -> None:
        """Print store status."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        with self._conn() as conn:
            fetch_count = conn.execute(
                "SELECT COUNT(*) FROM tds_fetch_log WHERE status='ok'"
            ).fetchone()[0]
            article_count = conn.execute(
                "SELECT COUNT(*) FROM tds_articles"
            ).fetchone()[0]
            topic_days = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM tds_topic_days"
            ).fetchone()[0]

        # check last N days
        missing_fetch = [
            (today - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(1, days + 1)
            if not self.is_fetched(today - timedelta(days=i))
        ]
        missing_topics = [
            d for i in range(1, days + 1)
            if self.is_fetched(d := (today - timedelta(days=i)))
            and not self._topics_computed(d)
        ]

        print(f"\n{'─'*50}")
        print(f"  TDSStore 狀態")
        print(f"{'─'*50}")
        print(f"  DB 路徑:       {self.db_path}")
        print(f"  已抓取天數:    {fetch_count} 天")
        print(f"  文章總數:      {article_count:,} 篇")
        print(f"  主題計算天數:  {topic_days} 天")
        print(f"  過去{days}天缺抓:  {len(missing_fetch)} 天 {missing_fetch[:5]}")
        print(f"  待計算主題:    {len(missing_topics)} 天")
        print(f"{'─'*50}\n")

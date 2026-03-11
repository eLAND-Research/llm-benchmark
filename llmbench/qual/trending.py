"""Hot topics ranking using TDS direct API + LiteLLM."""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .tds_direct import tds_search

LITELLM_URL = "https://llmgw.elandai.cloud/v1/chat/completions"
LITELLM_API_KEY = "sk-MpF28Nob8sv4ZnD2DwYuVA"
DEFAULT_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# LiteLLM helper
# ---------------------------------------------------------------------------

def _chat(messages: List[Dict], model: str = DEFAULT_MODEL, max_tokens: int = 2000) -> str:
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        LITELLM_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LITELLM_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_days(days: int = 5, max_per_day: int = 50) -> List[Dict[str, Any]]:
    """Fetch hot news for past N days, each article includes comment_count."""
    today = datetime.now()
    all_news: List[Dict[str, Any]] = []

    for i in range(1, days + 1):
        day = today - timedelta(days=i)
        ym = day.strftime("%y%m")
        result = tds_search(
            target_db=[f"WH_News_2%20{ym}%", f"WH_News_1%20{ym}%"],
            start_dt=day.strftime("%Y/%m/%d 00:00:00.000"),
            end_dt=day.strftime("%Y/%m/%d 23:59:59.999"),
            sort_field="comment_count",
            max_record=max_per_day,
            result_field=["id", "content", "comment_count", "post_time"],
        )
        items = result.get("result_list", [])
        for item in items:
            item["_date"] = day.strftime("%m/%d")
        all_news.extend(items)

    return all_news


# ---------------------------------------------------------------------------
# Topic ranking
# ---------------------------------------------------------------------------

def get_hot_topics(
    days: int = 5,
    top_n: int = 10,
    max_per_day: int = 50,
    model: str = DEFAULT_MODEL,
) -> List[Dict[str, Any]]:
    """
    取得過去 N 天的熱門主題排行榜。

    Returns:
        List of topics, sorted by total_comments desc:
        [
          {
            "rank": 1,
            "topic": "美伊衝突",
            "total_comments": 12345,
            "article_count": 18,
            "summary": "...",
            "representative": "...",  # 最具代表性文章摘要
            "dates": ["03/01", "02/28"]
          }, ...
        ]
    """
    news = _fetch_days(days=days, max_per_day=max_per_day)
    if not news:
        return []

    # 整理成 LLM 可讀格式（節省 token，只送摘要 + comment_count）
    articles_text = []
    for i, n in enumerate(news):
        snippet = re.sub(r"<[^>]+>", "", n.get("content", ""))[:100].strip()
        count = int(n.get("comment_count", 0) or 0)
        articles_text.append(f"[{i}] ({n['_date']}) 留言:{count} | {snippet}")

    prompt_articles = "\n".join(articles_text)

    messages = [
        {
            "role": "system",
            "content": (
                "你是台灣新聞分析師。根據提供的新聞列表（含留言數），"
                "將相關新聞歸納成主題，並依據各主題的總留言數排出熱門排行榜。"
                f"請回傳前 {top_n} 名，格式為 JSON：\n"
                '{"topics": [{"rank": 1, "topic": "主題名稱", "total_comments": 數字, '
                '"article_count": 數字, "summary": "50字內摘要", '
                '"representative": "最具代表性的標題或摘要（30字內）", '
                '"dates": ["03/01"]}]}'
            ),
        },
        {
            "role": "user",
            "content": f"以下是過去{days}天的熱門新聞（共{len(news)}筆）：\n\n{prompt_articles}",
        },
    ]

    raw = _chat(messages, model=model, max_tokens=2000)
    data = json.loads(raw)
    return data.get("topics", [])


def _fetch_week(start: datetime, end: datetime, max_record: int = 50) -> List[Dict[str, Any]]:
    """Fetch hot news for a date range, covering multi-month DBs if needed."""
    # Collect all year-months spanned by the range
    yms = set()
    cur = start
    while cur <= end:
        yms.add(cur.strftime("%y%m"))
        cur += timedelta(days=1)

    target_db = []
    for ym in sorted(yms):
        target_db += [f"WH_News_1%20{ym}%", f"WH_News_2%20{ym}%"]

    result = tds_search(
        target_db=target_db,
        start_dt=start.strftime("%Y/%m/%d 00:00:00.000"),
        end_dt=end.strftime("%Y/%m/%d 23:59:59.999"),
        sort_field="comment_count",
        max_record=max_record,
        result_field=["id", "content", "comment_count", "post_time"],
    )
    return result.get("result_list", [])


def get_trend_analysis(
    weeks: int = 4,
    max_per_week: int = 50,
    top_n: int = 10,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """
    分析過去 N 週新聞，找出快速竄升與正在退燒的主題。

    Returns:
        {
          "rising": [...],   # 快速竄升
          "cooling": [...],  # 正在退燒
          "periods": [{"label": "W1", "start": "02/03", "end": "02/09"}, ...]
        }
    """
    today = datetime.now()

    # 建立週期分桶（W1=最舊, W4=最新）
    periods = []
    for w in range(weeks, 0, -1):
        end_day = today - timedelta(days=(w - 1) * 7)
        start_day = end_day - timedelta(days=6)
        if start_day > today:
            continue
        if end_day > today:
            end_day = today
        periods.append({
            "label": f"W{weeks - w + 1}",
            "start": start_day,
            "end": end_day,
        })

    # 每週抓資料
    weekly_blocks = []
    for p in periods:
        news = _fetch_week(p["start"], p["end"], max_record=max_per_week)
        lines = []
        for n in news:
            snippet = re.sub(r"<[^>]+>", "", n.get("content", ""))[:80].strip()
            count = int(n.get("comment_count", 0) or 0)
            lines.append(f"  留言:{count} | {snippet}")
        weekly_blocks.append(
            f"【{p['label']} {p['start'].strftime('%m/%d')}~{p['end'].strftime('%m/%d')}】\n"
            + "\n".join(lines)
        )

    prompt_body = "\n\n".join(weekly_blocks)

    week_labels = [p["label"] for p in periods]

    messages = [
        {
            "role": "system",
            "content": (
                "你是台灣新聞趨勢分析師。根據各週的熱門新聞（含留言數），歸納主題並分析趨勢。\n\n"
                "分析步驟：\n"
                "1. 將相似新聞歸納成主題（如「美伊衝突」「關稅戰」「國防預算」）\n"
                "2. 估算每個主題在各週的總留言數（該週所有相關文章留言數加總）\n"
                "3. 判斷趨勢：\n"
                "   - 快速竄升：最後一週或兩週留言數明顯高於第一、二週（含全新爆發議題）\n"
                "   - 正在退燒：第一、二週留言數高，最後一週明顯下降\n"
                "4. 每類各列出 5~8 個主題，不夠就列出所有符合的\n\n"
                f"週期標籤：{week_labels}（W1=最舊，W{weeks}=最新）\n\n"
                f"回傳 JSON（weekly_comments 陣列長度必須等於 {weeks}）：\n"
                '{"rising": [{"topic": "主題名稱", "summary": "40字內摘要", '
                f'"weekly_comments": [W1總留言, ..., W{weeks}總留言], "trend_note": "竄升原因一句話"}}], '
                '"cooling": [{"topic": "主題名稱", "summary": "40字內摘要", '
                f'"weekly_comments": [W1總留言, ..., W{weeks}總留言], "trend_note": "退燒原因一句話"}}]}}'
            ),
        },
        {
            "role": "user",
            "content": (
                f"以下是過去 {weeks} 週（共 {sum(len(w.split(chr(10))) for w in weekly_blocks)} 筆）的熱門新聞資料，"
                "請仔細分析：\n\n" + prompt_body
            ),
        },
    ]

    raw = _chat(messages, model=model, max_tokens=3000)
    data = json.loads(raw)

    return {
        "rising": data.get("rising", []),
        "cooling": data.get("cooling", []),
        "periods": [
            {"label": p["label"], "start": p["start"].strftime("%m/%d"), "end": p["end"].strftime("%m/%d")}
            for p in periods
        ],
    }


def _sparkline(values: List[int]) -> str:
    """Render a compact ASCII sparkline from weekly values."""
    blocks = " ▁▂▃▄▅▆▇█"
    if not values or max(values) == 0:
        return "─" * len(values)
    hi = max(values)
    return "".join(blocks[min(8, int(v / hi * 8))] for v in values)


def _wow_changes(values: List[int]) -> List[str]:
    """Week-over-week % change labels."""
    out = ["—"]
    for i in range(1, len(values)):
        prev = values[i - 1]
        curr = values[i]
        if prev == 0:
            out.append("new" if curr > 0 else "—")
        else:
            pct = (curr - prev) / prev * 100
            sign = "+" if pct >= 0 else ""
            out.append(f"{sign}{pct:.0f}%")
    return out


def _trend_velocity(values: List[int]) -> str:
    """Classify trend momentum from weekly values."""
    if len(values) < 2:
        return ""
    first_half = sum(values[: len(values) // 2]) or 1
    second_half = sum(values[len(values) // 2 :]) or 0
    ratio = second_half / first_half
    if ratio >= 2.0:
        return "急速加速 🚀"
    if ratio >= 1.3:
        return "穩定上升 ↗"
    if ratio >= 0.8:
        return "持平震盪 ↔"
    if ratio >= 0.5:
        return "緩慢退燒 ↘"
    return "快速冷卻 ❄"


def _peak_week(values: List[int], periods: List[Dict]) -> str:
    if not values:
        return ""
    idx = values.index(max(values))
    if idx < len(periods):
        p = periods[idx]
        return f"{p['label']}({p['start']}~{p['end']})"
    return f"W{idx+1}"


def _print_topic(t: Dict[str, Any], periods: List[Dict], icon: str) -> None:
    weekly = [int(v or 0) for v in t.get("weekly_comments", [])]
    wow = _wow_changes(weekly)
    spark = _sparkline(weekly)
    velocity = _trend_velocity(weekly)
    peak = _peak_week(weekly, periods)
    total = sum(weekly)

    print(f"\n  {icon} {t['topic']}  [{velocity}]")
    print(f"     {t.get('summary', '')}")
    print(f"     走勢圖: {spark}  (總留言: {total:,}  |  峰值: {peak})")

    # 逐週數據列
    week_row = "  →  ".join(
        f"{p['label']}:{weekly[i]:,}({wow[i]})" if i < len(weekly) else ""
        for i, p in enumerate(periods)
    )
    print(f"     {week_row}")
    print(f"     └─ {t.get('trend_note', '')}")


def print_trend_analysis(result: Dict[str, Any]) -> None:
    """Pretty-print trend analysis with trend metrics."""
    periods = result.get("periods", [])
    period_labels = "  |  ".join(f"{p['label']}({p['start']}~{p['end']})" for p in periods)

    print(f"\n{'='*70}")
    print("  📈 快速竄升主題")
    print(f"  週期: {period_labels}")
    print(f"{'='*70}")
    for t in result.get("rising", []):
        _print_topic(t, periods, "🔥")

    print(f"\n{'='*70}")
    print("  📉 正在退燒主題")
    print(f"{'='*70}")
    for t in result.get("cooling", []):
        _print_topic(t, periods, "❄️ ")

    print(f"\n{'='*70}\n")


def print_ranking(topics: List[Dict[str, Any]]) -> None:
    """Pretty-print the hot topics ranking."""
    print(f"\n{'='*60}")
    print("  📰 熱門主題排行榜")
    print(f"{'='*60}")
    for t in topics:
        rank = t.get("rank", "?")
        topic = t.get("topic", "")
        total = t.get("total_comments", 0)
        count = t.get("article_count", 0)
        summary = t.get("summary", "")
        dates = ", ".join(t.get("dates", []))
        print(f"\n#{rank}  {topic}")
        print(f"    總留言數: {total:,}  |  相關文章: {count} 篇  |  日期: {dates}")
        print(f"    {summary}")
    print(f"\n{'='*60}\n")

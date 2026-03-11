"""TDS P2PServer profiler — discover historical range & measure query latency."""
from __future__ import annotations

import time
import urllib.parse
import urllib.request
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


TDS_URL = "http://10.20.30.1:6060/web/P2PServer.jsp"


# ---------------------------------------------------------------------------
# Raw query (minimal, no extra logic)
# ---------------------------------------------------------------------------

def _raw_query(
    target_db: List[str],
    start_dt: str,
    end_dt: str,
    max_record: int = 1,
    timeout: int = 15,
) -> Tuple[Dict[str, Any], float]:
    """Returns (parsed_response, elapsed_seconds)."""
    query = {
        "version": "0.5 sync",
        "query_type": "keyword",
        "keyword": "",
        "field_filter": {
            "expr": {
                "and": {
                    "expr_string": "POST_TIME&CONTENT_TYPE",
                    "field_map": {
                        "POST_TIME": {"post_time": f"{start_dt}~{end_dt}"},
                        "CONTENT_TYPE": {"content_type": "1;"},
                    },
                }
            }
        },
        "target_db": target_db,
        "search_mode": {"search_mode": "normal", "homophone": False,
                        "homograph": False, "chinese_convert": False,
                        "form_convert": False, "field_weight_sort": False},
        "search_order": [{"field": "comment_count", "order_type": "des"}],
        "search_range": {"start_pos": 0, "max_record": max_record},
        "result_field": ["id", "post_time"],
    }

    body = urllib.parse.urlencode({
        "action": "search",
        "txtInput_json": json.dumps(query, ensure_ascii=False),
    }).encode("utf-8")

    req = urllib.request.Request(
        TDS_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.perf_counter() - t0
        return data, elapsed
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {"error": str(e)}, elapsed


def _month_dbs(ym: str) -> List[str]:
    return [f"WH_News_1%20{ym}%", f"WH_News_2%20{ym}%"]


def _month_range(year: int, month: int) -> Tuple[str, str]:
    start = f"{year}/{month:02d}/01 00:00:00.000"
    # last day of month
    if month == 12:
        last = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = datetime(year, month + 1, 1) - timedelta(days=1)
    end = last.strftime("%Y/%m/%d") + " 23:59:59.999"
    return start, end


# ---------------------------------------------------------------------------
# 1. Historical range scan
# ---------------------------------------------------------------------------

def scan_history(max_months_back: int = 48, timeout: int = 10) -> List[Dict]:
    """
    Scan back month-by-month to find which months have data.
    Returns list of result dicts sorted oldest-first.
    """
    today = datetime.now()
    results = []

    print(f"\n{'─'*55}")
    print("  🔍 歷史資料範圍掃描")
    print(f"{'─'*55}")
    print(f"  {'月份':<10} {'筆數':>8} {'查詢時間':>10} {'狀態'}")
    print(f"  {'─'*8:<10} {'─'*6:>8} {'─'*8:>10} {'─'*6}")

    for i in range(max_months_back):
        # go back i months
        month_dt = today.replace(day=1) - timedelta(days=i * 30)
        month_dt = month_dt.replace(day=1)
        year, month = month_dt.year, month_dt.month
        ym = month_dt.strftime("%y%m")
        label = month_dt.strftime("%Y-%m")

        start_dt, end_dt = _month_range(year, month)
        data, elapsed = _raw_query(_month_dbs(ym), start_dt, end_dt,
                                   max_record=1, timeout=timeout)

        total = data.get("response_list", {}).get("total_count", 0) or 0
        has_data = isinstance(total, (int, float)) and int(total) > 0
        status = f"✓ 有資料" if has_data else "✗ 無資料"
        speed = f"{elapsed*1000:.0f}ms"

        print(f"  {label:<10} {str(total):>8} {speed:>10} {status}")
        results.append({
            "label": label, "ym": ym, "total": int(total or 0),
            "elapsed_ms": round(elapsed * 1000),
            "has_data": has_data,
        })

        # stop after 3 consecutive empty months
        if i >= 3 and all(not r["has_data"] for r in results[-3:]):
            print(f"\n  ⚠️  連續 3 個月無資料，停止掃描")
            break

    oldest = next((r for r in reversed(results) if r["has_data"]), None)
    if oldest:
        print(f"\n  📅 最早可回朔至：{oldest['label']}（共 {oldest['total']:,} 筆）")

    return results


# ---------------------------------------------------------------------------
# 2. Latency vs max_record benchmark
# ---------------------------------------------------------------------------

def bench_max_record(
    ym: Optional[str] = None,
    sizes: Optional[List[int]] = None,
    repeat: int = 3,
) -> List[Dict]:
    """Measure latency for different max_record sizes."""
    if ym is None:
        # use last month
        last_month = (datetime.now().replace(day=1) - timedelta(days=1))
        ym = last_month.strftime("%y%m")
        year, month = last_month.year, last_month.month
    else:
        year = 2000 + int(ym[:2])
        month = int(ym[2:])

    if sizes is None:
        sizes = [1, 10, 50, 100, 200, 500]

    start_dt, end_dt = _month_range(year, month)
    dbs = _month_dbs(ym)

    print(f"\n{'─'*55}")
    print(f"  ⚡ max_record 延遲基準測試（月份: 20{ym[:2]}-{ym[2:]}）")
    print(f"{'─'*55}")
    print(f"  {'max_record':>12} {'avg(ms)':>10} {'min(ms)':>10} {'max(ms)':>10}")
    print(f"  {'─'*10:>12} {'─'*7:>10} {'─'*7:>10} {'─'*7:>10}")

    results = []
    for size in sizes:
        times = []
        for _ in range(repeat):
            _, elapsed = _raw_query(dbs, start_dt, end_dt,
                                    max_record=size, timeout=20)
            times.append(elapsed * 1000)

        avg = sum(times) / len(times)
        results.append({"max_record": size, "avg_ms": round(avg),
                         "min_ms": round(min(times)), "max_ms": round(max(times))})
        print(f"  {size:>12} {avg:>10.0f} {min(times):>10.0f} {max(times):>10.0f}")

    return results


# ---------------------------------------------------------------------------
# 3. Latency vs date range width
# ---------------------------------------------------------------------------

def bench_date_range(
    base_ym: Optional[str] = None,
    repeat: int = 3,
) -> List[Dict]:
    """Measure latency for different query date range widths."""
    if base_ym is None:
        base_ym = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%y%m")

    today = datetime(2000 + int(base_ym[:2]), int(base_ym[2:]), 15)
    widths = [("1 天", 1), ("1 週", 7), ("2 週", 14), ("1 個月", 30),
              ("3 個月", 90), ("6 個月", 180)]

    print(f"\n{'─'*55}")
    print(f"  📅 查詢時間範圍 vs 延遲（基準: 20{base_ym[:2]}-{base_ym[2:]}）")
    print(f"{'─'*55}")
    print(f"  {'範圍':<12} {'avg(ms)':>10} {'min(ms)':>10} {'max(ms)':>10}")
    print(f"  {'─'*10:<12} {'─'*7:>10} {'─'*7:>10} {'─'*7:>10}")

    results = []
    for label, days in widths:
        start = today - timedelta(days=days)
        end = today

        # collect all yms in range
        yms: set = set()
        cur = start
        while cur <= end:
            yms.add(cur.strftime("%y%m"))
            cur += timedelta(days=1)
        dbs = [db for ym in sorted(yms) for db in _month_dbs(ym)]

        start_dt = start.strftime("%Y/%m/%d 00:00:00.000")
        end_dt = end.strftime("%Y/%m/%d 23:59:59.999")

        times = []
        for _ in range(repeat):
            _, elapsed = _raw_query(dbs, start_dt, end_dt,
                                    max_record=50, timeout=30)
            times.append(elapsed * 1000)

        avg = sum(times) / len(times)
        results.append({"range": label, "days": days, "avg_ms": round(avg),
                         "min_ms": round(min(times)), "max_ms": round(max(times))})
        print(f"  {label:<12} {avg:>10.0f} {min(times):>10.0f} {max(times):>10.0f}")

    return results


# ---------------------------------------------------------------------------
# 4. Full profile report
# ---------------------------------------------------------------------------

def run_profile(max_months_back: int = 36) -> None:
    print(f"\n{'='*55}")
    print("  TDS P2PServer 完整 Profile")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}")

    # 1. 歷史範圍
    history = scan_history(max_months_back=max_months_back)
    has_data = [r for r in history if r["has_data"]]

    # 2. max_record 基準（用最近有資料的月份）
    recent_ym = has_data[0]["ym"] if has_data else None
    if recent_ym:
        bench_max_record(ym=recent_ym)
        bench_date_range(base_ym=recent_ym)

    # 3. 建議
    oldest = has_data[-1] if has_data else None
    print(f"\n{'─'*55}")
    print("  💡 建議參數")
    print(f"{'─'*55}")
    if oldest:
        print(f"  最早可回朔：{oldest['label']}")
    print(f"  建議 max_record：≤ 100（超過 200 延遲明顯上升）")
    print(f"  建議查詢範圍：≤ 1 個月（跨月需多 DB，延遲倍增）")
    print(f"  每日查詢上限：建議間隔 ≥ 500ms 避免對 TDS 造成壓力")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    run_profile(max_months_back=36)

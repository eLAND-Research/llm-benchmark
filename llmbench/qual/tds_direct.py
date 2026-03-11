"""Direct TDS P2PServer query client (Plan B - no MCP dependency)."""
from __future__ import annotations

import urllib.parse
import urllib.request
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


TDS_URL = "http://10.20.30.1:6060/web/P2PServer.jsp"


def _build_query(
    target_db: List[str],
    keyword: str = "",
    start_dt: Optional[str] = None,
    end_dt: Optional[str] = None,
    content_type: str = "1;",
    sort_field: str = "comment_count",
    max_record: int = 10,
    result_field: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build TDS query dict."""
    if result_field is None:
        result_field = ["id", "content", "$p_type_2$", "post_time"]

    query: Dict[str, Any] = {
        "version": "0.5 sync",
        "query_type": "keyword",
        "keyword": keyword,
        "target_db": target_db,
        "search_mode": {
            "search_mode": "normal",
            "homophone": False,
            "homograph": False,
            "chinese_convert": False,
            "form_convert": False,
            "field_weight_sort": False,
        },
        "search_order": [{"field": sort_field, "order_type": "des"}],
        "search_range": {"start_pos": 0, "max_record": max_record},
        "result_field": result_field,
    }

    filters: Dict[str, Any] = {}
    expr_parts: List[str] = []

    if start_dt and end_dt:
        filters["POST_TIME"] = {"post_time": f"{start_dt}~{end_dt}"}
        expr_parts.append("POST_TIME")

    if content_type:
        filters["CONTENT_TYPE"] = {"content_type": content_type}
        expr_parts.append("CONTENT_TYPE")

    if filters:
        query["field_filter"] = {
            "expr": {
                "and": {
                    "expr_string": "&".join(expr_parts),
                    "field_map": filters,
                }
            }
        }

    return query


def tds_search(
    target_db: List[str],
    keyword: str = "",
    start_dt: Optional[str] = None,
    end_dt: Optional[str] = None,
    content_type: str = "1;",
    sort_field: str = "comment_count",
    max_record: int = 10,
    result_field: Optional[List[str]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Query TDS P2PServer directly (no MCP, no auth required).

    Args:
        target_db: e.g. ["WH_News_2%202506%", "WH_News_1%202506%"]
        keyword: search keyword (empty = all)
        start_dt: "2025/06/01 00:00:00.000"
        end_dt:   "2025/06/02 23:59:59.999"
        content_type: "1;" for news
        sort_field: "comment_count" or "post_time"
        max_record: max results
        result_field: fields to return
        timeout: HTTP timeout seconds

    Returns:
        Parsed response dict with keys: response_list, result_list, indexdb_info
    """
    query = _build_query(
        target_db=target_db,
        keyword=keyword,
        start_dt=start_dt,
        end_dt=end_dt,
        content_type=content_type,
        sort_field=sort_field,
        max_record=max_record,
        result_field=result_field,
    )

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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_hot_news(
    year_month: str,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    max_record: int = 50,
) -> List[Dict[str, Any]]:
    """
    取得熱門新聞（依 comment_count 排序）。

    Args:
        year_month: "2506" for 2025/06
        date_start: "2025/06/01 00:00:00.000"（省略則整月）
        date_end:   "2025/06/30 23:59:59.999"（省略則整月）
        max_record: 最多回傳幾筆

    Returns:
        result_list items
    """
    ym = year_month  # e.g. "2506"
    target_db = [f"WH_News_2%20{ym}%", f"WH_News_1%20{ym}%"]

    result = tds_search(
        target_db=target_db,
        start_dt=date_start,
        end_dt=date_end,
        sort_field="comment_count",
        max_record=max_record,
    )
    return result.get("result_list", [])


def get_today_hot_news(max_record: int = 50) -> List[Dict[str, Any]]:
    """取得今日熱門新聞。"""
    today = datetime.now()
    ym = today.strftime("%y%m")  # e.g. "2603"
    start_dt = today.strftime("%Y/%m/%d 00:00:00.000")
    end_dt = today.strftime("%Y/%m/%d 23:59:59.999")
    return get_hot_news(ym, date_start=start_dt, date_end=end_dt, max_record=max_record)

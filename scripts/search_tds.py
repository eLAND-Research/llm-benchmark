"""
透過 LangChain MCP Adapter 查詢 TDS MCP 服務。
用法: python scripts/search_tds.py
"""
import asyncio
import json

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.sse import sse_client

MCP_SSE_URL = "http://172.18.10.41:8888/sse"


def parse_result(result):
    """從 LangChain tool 回傳值中解析出 JSON data"""
    if isinstance(result, list) and len(result) > 0:
        item = result[0]
        text_val = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        if text_val:
            return json.loads(text_val)
    return None


def print_results(data):
    """格式化印出搜尋結果"""
    if not data:
        print("  無法解析回傳資料")
        return

    docs = data.get("results", [])
    summary = data.get("summary", {})
    total = summary.get("total_count", "?")
    valid = summary.get("valid_count", len(docs))
    query_time = summary.get("query_time", 0)

    print(f"  命中: {total:,} 筆 | 回傳: {valid} 筆 | 查詢耗時: {query_time:.2f}s\n")

    if not docs:
        print("  （無結果）")
        return

    for i, doc in enumerate(docs, 1):
        title = doc.get("title", "無標題")
        content = doc.get("content", "")
        # 取前 120 字作摘要，清理換行
        snippet = content[:120].replace("<BR>", " ").replace("\n", " ").strip()

        print(f"  {i}. {title}")
        if snippet:
            print(f"     {snippet}...")
        print()


async def main():
    print("連線到 TDS MCP server...\n")
    async with sse_client(MCP_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            tool_map = {t.name: t for t in tools}
            print(f"已載入 {len(tools)} 個 tools: {list(tool_map.keys())}\n")

            # 健康檢查
            health = parse_result(await tool_map["tds_health"].ainvoke({}))
            print(f"TDS 狀態: {health.get('status')}\n")

            # 搜尋三個分類
            searches = [
                ("新聞 (news)", ["news"]),
                ("Facebook", ["facebook"]),
                ("Dcard", ["dcard"]),
            ]

            for label, categories in searches:
                print(f"{'='*60}")
                print(f" 川普 & 關稅 — {label}")
                print(f"{'='*60}")
                result = await tool_map["easy_search"].ainvoke({
                    "categories": categories,
                    "keyword": "川普 & 關稅",
                    "top_k": 5,
                    "month_range": {"start": "202501", "end": "202602"},
                    "sort_by": "time"
                })
                data = parse_result(result)
                print_results(data)


if __name__ == "__main__":
    asyncio.run(main())

"""OpView MCP client via LiteLLM proxy (HTTPS + Bearer Token).

Architecture:
  Client → LiteLLM Proxy (llmgw.elandai.cloud) → MCP Server: opview_tds → OpView TDS

Unlike the SSE-based MCP client used by Researcher, this client uses
JSON-RPC 2.0 over plain HTTPS with Bearer Token authentication.

Shared quota: rpm=30, tpm=200K, max_parallel=5.
Use ``max_parallel`` in :class:`OpViewMCPConfig` to cap concurrent requests.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class OpViewMCPClient:
    """Synchronous client for OpView MCP via LiteLLM proxy.

    Parameters
    ----------
    base_url:
        LiteLLM proxy URL, e.g. ``"https://llmgw.elandai.cloud"``.
    api_key:
        Bearer token for authentication.
    mcp_alias:
        MCP server alias registered in LiteLLM, default ``"opview_tds"``.
    timeout:
        HTTP timeout in seconds (default 30).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        mcp_alias: str = "opview_tds",
        timeout: int = 30,
        max_parallel: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.mcp_alias = mcp_alias
        self.timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # LiteLLM proxy requires both types, otherwise returns 406
            "Accept": "application/json, text/event-stream",
        }
        # Throttle concurrent requests to respect shared quota (max_parallel=5)
        self._semaphore = threading.Semaphore(max_parallel)

    # ------------------------------------------------------------------
    # Low-level JSON-RPC helpers
    # ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return all tools exposed by the MCP server."""
        resp = requests.post(
            f"{self.base_url}/mcp/{self.mcp_alias}/list_tools",
            headers=self._headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = self._parse_response(resp.text)
        return data["result"]["tools"]

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invoke an MCP tool and return the parsed result dict.

        Parameters
        ----------
        tool_name:
            Name of the tool to call, e.g. ``"easy_search"``.
        arguments:
            Tool arguments (will be passed as-is).

        Returns
        -------
        dict
            Parsed JSON payload from ``result.content[0]["text"]``.

        Raises
        ------
        requests.HTTPError
            On non-2xx HTTP responses.
        RuntimeError
            When the MCP server returns a JSON-RPC error.
        """
        with self._semaphore:
            resp = requests.post(
                f"{self.base_url}/mcp/{self.mcp_alias}/call_tool",
                headers=self._headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments or {}},
                },
                timeout=self.timeout,
            )
        resp.raise_for_status()
        data = self._parse_response(resp.text)
        if "error" in data:
            raise RuntimeError(f"MCP error from {tool_name}: {data['error']}")
        content = data["result"]["content"]
        if data["result"].get("isError"):
            raise RuntimeError(f"Tool {tool_name} returned error: {content[0]['text']}")
        # result.content[0]["text"] is a JSON string that must be decoded
        text = content[0]["text"]
        return json.loads(text)

    @staticmethod
    def _parse_response(body: str) -> dict:
        """Parse response body — handles both plain JSON and SSE format.

        LiteLLM returns SSE (``event: message\\ndata: {...}\\n\\n``) when the
        client accepts ``text/event-stream``.  Extract the ``data:`` line and
        parse it as JSON.
        """
        body = body.strip()
        if body.startswith("{"):
            return json.loads(body)
        # SSE: find the last non-empty "data: ..." line
        for line in reversed(body.splitlines()):
            line = line.strip()
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        raise ValueError(f"Cannot parse response body: {body[:200]}")

    # ------------------------------------------------------------------
    # High-level tool wrappers
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Health check (no parameters)."""
        return self.call_tool("tds_health")

    def list_categories(self) -> List[Dict[str, Any]]:
        """Return all searchable categories."""
        result = self.call_tool("list_categories")
        return result.get("categories", [])

    def easy_search(
        self,
        categories: List[str],
        keyword: Optional[str] = None,
        top_k: int = 50,
        month_range: Optional[Dict[str, str]] = None,
        sort_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Simple keyword search.

        Parameters
        ----------
        categories:
            Category codes, e.g. ``["news", "facebook"]``.
        keyword:
            Search keyword; supports boolean operators ``& | ! ()``.
        top_k:
            Max results (default 50).
        month_range:
            Date range, e.g. ``{"start": "202601", "end": "202603"}``.
        sort_by:
            ``"time"`` or ``"score"``.
        """
        args: Dict[str, Any] = {"categories": categories}
        if keyword:
            args["keyword"] = keyword
        if top_k != 50:
            args["top_k"] = top_k
        else:
            args["top_k"] = top_k
        if month_range:
            args["month_range"] = month_range
        if sort_by:
            args["sort_by"] = sort_by
        return self.call_tool("easy_search", args)

    def guided_search(
        self,
        categories: List[str],
        keyword: Optional[str] = None,
        top_k: int = 50,
        month_range: Optional[Dict[str, str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        output: str = "raw",
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Advanced search with optional filters and summary output.

        Parameters
        ----------
        output:
            ``"raw"`` (default) or ``"summary"`` (LLM-generated summary).
        filters:
            AND filter conditions, e.g. ``{"author": "some_author"}``.
        collections:
            Explicit collection names (merged with categories).
        """
        args: Dict[str, Any] = {"categories": categories, "output": output}
        if keyword:
            args["keyword"] = keyword
        args["top_k"] = top_k
        if month_range:
            args["month_range"] = month_range
        if filters:
            args["filters"] = filters
        if collections:
            args["collections"] = collections
        return self.call_tool("guided_search", args)

    def hot_news(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent hot news sorted by comment count.

        Parameters
        ----------
        days:
            Look-back window in days (default 7).
        limit:
            Max results (default 10).
        """
        result = self.call_tool("hot_news", {"days": days, "limit": limit})
        return result.get("items", [])

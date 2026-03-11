"""Researcher agent -- fetches raw materials from the TDS MCP service.

This agent is a pure Python implementation (no LLM required).  It connects
to a TDS MCP server via SSE, runs ``easy_search`` for every
:class:`~llmbench.qual.config.SearchConfig` entry, converts the results into
:class:`~llmbench.qual.schemas.RawMaterial` objects, deduplicates, and returns
the collected list.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.sse import sse_client

from llmbench.qual.config import DataSourceConfig, SearchConfig
from llmbench.qual.schemas import RawMaterial

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_mcp_result(raw: Any) -> Optional[Dict[str, Any]]:
    """Extract the JSON payload from an MCP tool invocation result.

    The TDS MCP ``easy_search`` tool returns a list whose first element
    contains a ``text`` field holding a JSON string.  This helper mirrors
    the ``parse_result()`` function in ``scripts/search_tds.py``.
    """
    if isinstance(raw, list) and len(raw) > 0:
        item = raw[0]
        text_val = (
            item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        )
        if text_val:
            try:
                return json.loads(text_val)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Failed to decode MCP result JSON: %s", exc)
                return None
    return None


def _dedup_key(mat: RawMaterial) -> str:
    """Return a deduplication key for a :class:`RawMaterial`.

    Uses ``title + content[:100]`` so that articles with the same headline
    and opening text are considered duplicates even if trailing content
    differs slightly.
    """
    return f"{mat.title}||{mat.content[:100]}"


def _result_to_raw_materials(
    data: Dict[str, Any],
    search: SearchConfig,
) -> List[RawMaterial]:
    """Convert the parsed JSON payload into a list of :class:`RawMaterial`.

    Parameters
    ----------
    data:
        Parsed JSON from ``_parse_mcp_result``.  Expected to contain a
        ``results`` key whose value is a list of dicts, each with at least
        ``title`` and ``content``.
    search:
        The :class:`SearchConfig` that produced this result (used to
        populate ``keyword``, ``month_range``, and ``source_category``).
    """
    materials: List[RawMaterial] = []
    results = data.get("results", [])

    # Build the month_range dict to store on each RawMaterial.
    month_range: Dict[str, str] = search.month_range or {"start": "", "end": ""}

    # The category string is a comma-joined representation when multiple
    # categories are searched at once; individual result docs do not carry
    # their own category tag from TDS so we record the search-level info.
    source_category = ",".join(search.categories)

    for doc in results:
        title = doc.get("title", "")
        content = doc.get("content", "")
        if not title and not content:
            logger.debug("Skipping empty result document (no title or content)")
            continue
        materials.append(
            RawMaterial(
                source_category=source_category,
                title=title,
                content=content,
                keyword=search.keyword,
                month_range=month_range,
            )
        )

    return materials


# ---------------------------------------------------------------------------
# Researcher agent
# ---------------------------------------------------------------------------


class Researcher:
    """Researcher agent that fetches raw materials from TDS MCP.

    Parameters
    ----------
    config:
        A :class:`DataSourceConfig` specifying the MCP server URL and one
        or more :class:`SearchConfig` entries to execute.

    Example
    -------
    >>> from llmbench.qual.config import DataSourceConfig, SearchConfig
    >>> cfg = DataSourceConfig(
    ...     mcp_url="http://172.18.10.41:8888/sse",
    ...     searches=[
    ...         SearchConfig(categories=["news"], keyword="AI", top_k=10),
    ...     ],
    ... )
    >>> researcher = Researcher(cfg)
    >>> materials = asyncio.run(researcher.fetch())
    """

    def __init__(self, config: DataSourceConfig) -> None:
        self.config = config

    # -- public API ---------------------------------------------------------

    async def fetch(self) -> List[RawMaterial]:
        """Connect to TDS MCP, run all configured searches, and return
        deduplicated :class:`RawMaterial` items.

        Raises
        ------
        ConnectionError
            If the MCP server is unreachable or the session cannot be
            established.
        RuntimeError
            If the ``easy_search`` tool is not available on the MCP server.
        """
        all_materials: List[RawMaterial] = []

        logger.info(
            "Connecting to TDS MCP server at %s ...", self.config.mcp_url,
        )

        try:
            async with sse_client(self.config.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await load_mcp_tools(session)
                    tool_map = {t.name: t for t in tools}

                    logger.info(
                        "MCP session initialised. Available tools: %s",
                        list(tool_map.keys()),
                    )

                    if "easy_search" not in tool_map:
                        raise RuntimeError(
                            "TDS MCP server does not expose an 'easy_search' tool. "
                            f"Available tools: {list(tool_map.keys())}"
                        )

                    for idx, search in enumerate(self.config.searches, 1):
                        results = await self._execute_search(
                            tool_map, search, idx, len(self.config.searches),
                        )
                        all_materials.extend(results)

        except ConnectionError:
            logger.error(
                "Failed to connect to TDS MCP server at %s",
                self.config.mcp_url,
            )
            raise
        except Exception as exc:
            # Re-raise RuntimeError (our own) as-is; wrap anything else
            # that is not already a ConnectionError / RuntimeError.
            if isinstance(exc, (RuntimeError, ConnectionError)):
                raise
            logger.error("Unexpected error during MCP fetch: %s", exc)
            raise ConnectionError(
                f"MCP communication failure: {exc}"
            ) from exc

        # Deduplicate
        deduped = self._deduplicate(all_materials)

        logger.info(
            "Researcher finished: %d raw materials collected, %d after dedup.",
            len(all_materials),
            len(deduped),
        )

        return deduped

    # -- private helpers ----------------------------------------------------

    async def _execute_search(
        self,
        tool_map: Dict[str, Any],
        search: SearchConfig,
        index: int,
        total: int,
    ) -> List[RawMaterial]:
        """Run a single ``easy_search`` call and convert results.

        Returns an empty list (rather than raising) when the search itself
        fails, so that one bad query does not abort the entire fetch.
        """
        logger.info(
            "[%d/%d] Searching categories=%s keyword=%r top_k=%d",
            index,
            total,
            search.categories,
            search.keyword,
            search.top_k,
        )

        invoke_args: Dict[str, Any] = {
            "categories": search.categories,
            "keyword": search.keyword,
            "top_k": search.top_k,
            "sort_by": search.sort_by,
        }
        if search.month_range is not None:
            invoke_args["month_range"] = search.month_range

        try:
            raw_result = await tool_map["easy_search"].ainvoke(invoke_args)
        except Exception as exc:
            logger.warning(
                "[%d/%d] easy_search invocation failed for keyword=%r: %s",
                index,
                total,
                search.keyword,
                exc,
            )
            return []

        data = _parse_mcp_result(raw_result)
        if data is None:
            logger.warning(
                "[%d/%d] Could not parse MCP response for keyword=%r",
                index,
                total,
                search.keyword,
            )
            return []

        # Log summary info if available
        summary = data.get("summary", {})
        total_count = summary.get("total_count", "?")
        valid_count = summary.get("valid_count", "?")
        query_time = summary.get("query_time", 0)
        logger.info(
            "[%d/%d] Results -- total_count=%s valid_count=%s query_time=%.2fs",
            index,
            total,
            total_count,
            valid_count,
            query_time,
        )

        materials = _result_to_raw_materials(data, search)
        logger.info(
            "[%d/%d] Converted %d results into RawMaterial objects.",
            index,
            total,
            len(materials),
        )

        return materials

    @staticmethod
    def _deduplicate(materials: List[RawMaterial]) -> List[RawMaterial]:
        """Remove duplicate materials based on ``title + content[:100]``."""
        seen: set[str] = set()
        unique: List[RawMaterial] = []
        for mat in materials:
            key = _dedup_key(mat)
            if key not in seen:
                seen.add(key)
                unique.append(mat)
        return unique

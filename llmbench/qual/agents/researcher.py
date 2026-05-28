"""Researcher agent -- fetches raw materials from the TDS MCP service.

This agent is a pure Python implementation (no LLM required).  It supports
two backends:

1. **SSE-based MCP** (default): connects via ``mcp.client.sse`` to a direct
   TDS MCP server (``DataSourceConfig.mcp_url``).
2. **OpView MCP via LiteLLM** (optional): uses HTTPS + Bearer Token when
   ``DataSourceConfig.opview_mcp`` is configured.

The backend is selected automatically based on the config.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

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
        """Fetch raw materials (auto-selects backend by priority).

        Priority: ``challenge`` > ``taiwan_md`` > ``school_qa`` > ``threads``
                  > ``opview_mcp`` > SSE MCP (``mcp_url``)

        Raises
        ------
        ConnectionError
            If the backend is unreachable.
        RuntimeError
            If the ``easy_search`` tool is not available.
        """
        if self.config.challenge is not None:
            return await self._fetch_via_challenge()
        if self.config.taiwan_md is not None:
            return await self._fetch_via_taiwan_md()
        if self.config.exam_bank is not None:
            return await self._fetch_via_exam_bank()
        if self.config.school_qa is not None:
            return await self._fetch_via_school_qa()
        if self.config.threads is not None:
            return await self._fetch_via_threads()
        if self.config.opview_mcp is not None:
            return await self._fetch_via_opview_mcp()
        return await self._fetch_via_sse()

    # -- backend: Challenge JSONL --------------------------------------------

    async def _fetch_via_challenge(self) -> List[RawMaterial]:
        """Load materials from a challenge's inline JSONL content."""
        import json as _json
        cfg = self.config.challenge
        logger.info("Using Challenge JSONL data source (keyword=%r)", cfg.keyword)

        materials: List[RawMaterial] = []
        for line in cfg.data_jsonl.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = _json.loads(line)
            except _json.JSONDecodeError:
                continue

            text = doc.get("text") or doc.get("content", "")
            title = doc.get("title", text[:60])
            if not text:
                continue

            month = doc.get("month", "")
            materials.append(RawMaterial(
                source_category=doc.get("source_category", "challenge"),
                title=title,
                content=text,
                keyword=doc.get("keyword", cfg.keyword),
                month_range={"start": month, "end": month},
            ))

        logger.info("Researcher finished (Challenge): %d materials loaded", len(materials))
        return materials

    # -- backend: Taiwan.md knowledge base -----------------------------------

    async def _fetch_via_taiwan_md(self) -> List[RawMaterial]:
        """Fetch articles from the Taiwan.md GitHub repository."""
        import asyncio
        from llmbench.qual.taiwan_md_source import load_taiwan_md_materials

        cfg = self.config.taiwan_md
        logger.info(
            "Using Taiwan.md data source (lang=%s, categories=%s, limit=%s)",
            cfg.lang, cfg.categories, cfg.limit,
        )
        loop = asyncio.get_event_loop()
        materials = await loop.run_in_executor(
            None,
            lambda: load_taiwan_md_materials(
                categories=cfg.categories,
                lang=cfg.lang,
                limit=cfg.limit,
                timeout=cfg.timeout,
            ),
        )
        logger.info("Researcher finished (Taiwan.md): %d materials loaded", len(materials))
        return materials

    # -- backend: Exam Bank (PDF download + parse) ---------------------------

    async def _fetch_via_exam_bank(self) -> List[RawMaterial]:
        """Download exam PDFs from manifest/zips and extract text."""
        import asyncio
        from llmbench.qual.exam_bank_source import load_exam_bank_materials

        cfg = self.config.exam_bank
        logger.info(
            "Using Exam Bank data source (level=%s, subjects=%s, manifest=%s, zips=%s)",
            cfg.level, cfg.subjects, cfg.manifest, cfg.zip_archives,
        )
        loop = asyncio.get_event_loop()
        materials = await loop.run_in_executor(
            None,
            lambda: load_exam_bank_materials(
                manifest=cfg.manifest,
                zip_archives=cfg.zip_archives,
                level=cfg.level,
                subjects=cfg.subjects,
                grades=cfg.grades,
                cache_dir=cfg.cache_dir,
                limit=cfg.limit,
                download_timeout=cfg.download_timeout,
                max_download_workers=cfg.max_download_workers,
                parse_questions=cfg.parse_questions,
            ),
        )
        logger.info("Researcher finished (Exam Bank): %d materials loaded", len(materials))
        return materials

    # -- backend: School QA (國小/國中 curriculum) ----------------------------

    async def _fetch_via_school_qa(self) -> List[RawMaterial]:
        """Load built-in or custom curriculum materials for school QA."""
        import asyncio
        from llmbench.qual.school_qa_source import load_school_qa_materials

        cfg = self.config.school_qa
        logger.info(
            "Using School QA data source (level=%s, subjects=%s, limit=%s)",
            cfg.level, cfg.subjects, cfg.limit,
        )
        loop = asyncio.get_event_loop()
        materials = await loop.run_in_executor(
            None,
            lambda: load_school_qa_materials(
                level=cfg.level,
                subjects=cfg.subjects,
                data_jsonl=cfg.data_jsonl,
                limit=cfg.limit,
            ),
        )
        logger.info("Researcher finished (School QA): %d materials loaded", len(materials))
        return materials

    # -- backend: Threads local files ----------------------------------------

    async def _fetch_via_threads(self) -> List[RawMaterial]:
        """Load materials from one or more local Threads scraper directories."""
        import asyncio
        from llmbench.qual.threads_source import load_threads_materials

        all_materials: List[RawMaterial] = []
        loop = asyncio.get_event_loop()

        for cfg in self.config.threads:
            logger.info(
                "Using Threads local data source at %s (keyword=%r, limit=%s)",
                cfg.directory, cfg.keyword, cfg.limit,
            )
            materials = await loop.run_in_executor(
                None,
                lambda c=cfg: load_threads_materials(
                    directory=c.directory,
                    keyword=c.keyword,
                    include_replies=c.include_replies,
                    combine_replies=c.combine_replies,
                    min_like_count=c.min_like_count,
                    min_replies_count=c.min_replies_count,
                    min_repost_count=c.min_repost_count,
                    date_start=c.date_start,
                    date_end=c.date_end,
                    text_contains=c.text_contains,
                    min_text_length=c.min_text_length,
                    exclude_emoji_only=c.exclude_emoji_only,
                    limit=c.limit,
                ),
            )
            all_materials.extend(materials)

        logger.info("Researcher finished (Threads): %d materials total", len(all_materials))
        return all_materials

    # -- backend: OpView MCP (LiteLLM proxy) --------------------------------

    async def _fetch_via_opview_mcp(self) -> List[RawMaterial]:
        """Fetch using OpView MCP via LiteLLM proxy."""
        import asyncio
        from llmbench.qual.opview_mcp import OpViewMCPClient

        cfg = self.config.opview_mcp
        client = OpViewMCPClient(
            base_url=cfg.litellm_url,
            api_key=cfg.litellm_api_key,
            mcp_alias=cfg.mcp_alias,
            timeout=cfg.timeout,
        )

        logger.info(
            "Using OpView MCP backend at %s (alias=%s)",
            cfg.litellm_url,
            cfg.mcp_alias,
        )

        all_materials: List[RawMaterial] = []
        loop = asyncio.get_event_loop()

        for idx, search in enumerate(self.config.searches, 1):
            logger.info(
                "[%d/%d] Searching categories=%s keyword=%r top_k=%d (OpView MCP)",
                idx,
                len(self.config.searches),
                search.categories,
                search.keyword,
                search.top_k,
            )
            try:
                # OpViewMCPClient is synchronous; run in executor to avoid blocking
                result = await loop.run_in_executor(
                    None,
                    lambda s=search: client.easy_search(
                        categories=s.categories,
                        keyword=s.keyword,
                        top_k=s.top_k,
                        month_range=s.month_range,
                        sort_by=s.sort_by if s.sort_by else None,
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "[%d/%d] OpView MCP easy_search failed for keyword=%r: %s",
                    idx,
                    len(self.config.searches),
                    search.keyword,
                    exc,
                )
                continue

            # easy_search returns items in result["items"]
            items = result.get("items", [])
            summary = result.get("summary", {})
            logger.info(
                "[%d/%d] Results -- total_count=%s valid_count=%s query_time=%.2fs",
                idx,
                len(self.config.searches),
                summary.get("total_count", "?"),
                summary.get("valid_count", "?"),
                summary.get("query_time", 0),
            )

            month_range = search.month_range or {"start": "", "end": ""}
            source_category = ",".join(search.categories)
            for doc in items:
                title = doc.get("title") or ""
                content = doc.get("content", "")
                if not title and not content:
                    continue
                all_materials.append(
                    RawMaterial(
                        source_category=source_category,
                        title=title,
                        content=content,
                        keyword=search.keyword,
                        month_range=month_range,
                    )
                )

        deduped = self._deduplicate(all_materials)
        logger.info(
            "Researcher finished (OpView MCP): %d collected, %d after dedup.",
            len(all_materials),
            len(deduped),
        )
        return deduped

    # -- backend: SSE MCP (original) -----------------------------------------

    async def _fetch_via_sse(self) -> List[RawMaterial]:
        """Fetch using the original SSE-based MCP server."""
        from langchain_mcp_adapters.tools import load_mcp_tools
        from mcp import ClientSession
        from mcp.client.sse import sse_client

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
            if isinstance(exc, (RuntimeError, ConnectionError)):
                raise
            logger.error("Unexpected error during MCP fetch: %s", exc)
            raise ConnectionError(
                f"MCP communication failure: {exc}"
            ) from exc

        deduped = self._deduplicate(all_materials)
        logger.info(
            "Researcher finished (SSE MCP): %d collected, %d after dedup.",
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

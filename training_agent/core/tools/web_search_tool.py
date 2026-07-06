"""Web Search Tool.

T02 - 联网搜索工具，调用 search-service (OpenSERP)。
"""

import logging

import httpx

from core.tools.base import BaseTool
from core.config import settings

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Search the internet via search-service (OpenSERP)."""

    def __init__(self, search_url: str = "", engine: str = "", limit: int = 0):
        self._search_url = search_url or settings.search_service_url
        self._engine = engine or settings.search_default_engine
        self._limit = limit or settings.search_default_limit

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "在互联网上搜索最新信息。"
            "当知识库中没有相关信息、需要最新资讯、或问题涉及外部知识时使用此工具。"
        )

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词",
                        },
                        "engine": {
                            "type": "string",
                            "description": "搜索引擎: google, bing, duckduckgo, baidu",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def invoke(self, query: str, engine: str = "", **kwargs) -> str:
        engine = engine or self._engine
        url = f"{self._search_url}/search"
        params = {"q": query, "engine": engine, "limit": self._limit}

        logger.info(f"[WebSearchTool] q={query}, engine={engine}")

        try:
            with httpx.Client(timeout=30.0, trust_env=False) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.warning(f"[WebSearchTool] Timeout: {url}")
            return "本次联网搜索超时，已保留已有资料继续下一步。"
        except Exception as e:
            logger.error(f"[WebSearchTool] Error: {e}")
            return "本次联网搜索未能获取更多结果，已保留已有资料继续下一步。"

        status = data.get("status", "ok")
        results = data.get("results", [])
        if status == "upstream_failed":
            return "本次联网搜索未能获取更多结果，已保留已有资料继续下一步。"
        if status == "bad_request":
            return "联网搜索参数无效，已保留已有资料继续下一步。"
        if not results:
            return "未搜索到更多相关结果。"

        parts = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            parts.append(f"【{i}】{title}\n{snippet}\n链接: {url}")

        took_ms = data.get("took_ms", 0)
        fallback_engine = data.get("fallback_engine")
        cache_hit = data.get("cache_hit", False)
        actual_engine = fallback_engine or engine
        cache_suffix = "，缓存命中" if cache_hit else ""
        return f"搜索完成（{took_ms}ms，来源: {actual_engine}{cache_suffix}）：\n\n" + "\n\n".join(parts)

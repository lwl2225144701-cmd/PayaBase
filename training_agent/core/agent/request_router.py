"""Lightweight request router for single-chain execution (应用层门面).

规则路由逻辑下沉到 `core/domain/agent/router.py` 的 `RequestRoutingService`
（关键词由配置注入、支持否定词、按置信度排序）。本类负责：
- 从 `settings` 构造 `RoutingKeywordConfig` 注入领域服务；
- 保留 LLM 兜底路由（需要 llm_client + prompt，属应用/基础设施关注点）。
`RouteDecision` 现定义于领域层，此处再导出以保持兼容。
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from core.config import settings
from core.domain.agent.router import (
    RequestRoutingService,
    RouteDecision,
    RoutingKeywordConfig,
)
from core.llm.client import LLMClient
from core.prompts.router import ROUTE_CLASSIFIER_PROMPT

logger = logging.getLogger(__name__)

_ROUTE_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _build_keyword_config() -> RoutingKeywordConfig:
    """从配置构造路由关键词（支持配置化 / 热更新）。"""
    return RoutingKeywordConfig(
        pdf=settings.route_pdf_keywords,
        ppt=settings.route_ppt_keywords,
        summary=settings.route_summary_keywords,
        generation=settings.route_generation_keywords,
        rag_hint=settings.route_rag_hint_keywords,
        fallback=settings.route_fallback_keywords,
        negation=settings.route_negation_keywords,
    )


class RequestRouter:
    """Rule-first request router with optional small-model fallback."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client
        self._service = RequestRoutingService(_build_keyword_config())

    async def decide(
        self,
        *,
        query: str,
        has_attachments: bool,
        has_active_kb: bool,
    ) -> RouteDecision:
        decision = self._service.decide(
            query=query,
            has_attachments=has_attachments,
            has_active_kb=has_active_kb,
        )
        # 规则命中（非「无匹配」兜底）→ 直接返回；否则在存在 LLM 时走 LLM 兜底
        if not (decision.route == "fallback_chat" and decision.reason == "no_rule_match"):
            return decision
        if not self.llm:
            return decision
        return await self._llm_decide(query)

    async def _llm_decide(self, query: str) -> RouteDecision:
        loop = asyncio.get_running_loop()

        def call_llm() -> str:
            response = self.llm.chat(
                [
                    {"role": "system", "content": ROUTE_CLASSIFIER_PROMPT},
                    {"role": "user", "content": query},
                ],
                stream=False,
                temperature=0,
            )
            return (response or "").strip()

        started = loop.time()
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(_ROUTE_EXECUTOR, call_llm),
                timeout=settings.llm_classify_timeout,
            )
            route = RequestRoutingService.normalize_route(raw)
            elapsed_ms = int((loop.time() - started) * 1000)
            logger.info(f"[RequestRouter] llm route={route}, elapsed={elapsed_ms}ms, raw={raw[:80]}")
            return RouteDecision(route, "small_llm", f"llm_decision:{raw[:40]}", 0.70)
        except TimeoutError:
            logger.warning("[RequestRouter] LLM route timeout, fallback to fallback_chat")
            return RouteDecision("fallback_chat", "fallback", "router_timeout", 0.40)
        except Exception as exc:
            logger.warning(f"[RequestRouter] LLM route failed: {exc}")
            return RouteDecision("fallback_chat", "fallback", "router_failure", 0.40)

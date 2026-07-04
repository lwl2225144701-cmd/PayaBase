"""Lightweight request router for single-chain execution."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from core.config import settings
from core.llm.client import LLMClient
from core.prompts.router import ROUTE_CLASSIFIER_PROMPT

logger = logging.getLogger(__name__)

_ROUTE_EXECUTOR = ThreadPoolExecutor(max_workers=2)


SUMMARY_KEYWORDS = (
    "总结", "概括", "摘要", "提炼", "梳理", "归纳", "总结一下", "概述",
)
PDF_KEYWORDS = (
    "pdf", "PDF", "导出pdf", "导出 PDF", "生成pdf", "生成 PDF", "输出pdf", "输出 PDF", "下载pdf", "下载 PDF",
)
PPT_KEYWORDS = (
    "ppt", "PPT", "课件", "演示文稿", "汇报页", "幻灯片",
)
GENERATION_KEYWORDS = (
    "生成", "起草", "撰写", "写一份", "帮我写", "输出一份", "拟一份", "草案", "方案",
)
RAG_HINT_KEYWORDS = (
    "什么是", "如何", "怎么", "流程", "制度", "规范", "文档", "资料", "知识库", "附件",
    "在哪", "谁", "多久", "要求", "规则", "说明",
)
FALLBACK_KEYWORDS = (
    "你好", "hi", "hello", "早上好", "晚上好", "谢谢", "thank", "在吗",
)


@dataclass
class RouteDecision:
    route: str
    decision_source: str
    reason: str
    confidence: float


class RequestRouter:
    """Rule-first request router with optional small-model fallback."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    async def decide(
        self,
        *,
        query: str,
        has_attachments: bool,
        has_active_kb: bool,
    ) -> RouteDecision:
        text = (query or "").strip()
        lower = text.lower()

        if self._contains_any(text, PDF_KEYWORDS):
            return RouteDecision("pdf_generation", "rule", "matched_pdf_keywords", 0.98)

        if self._contains_any(text, PPT_KEYWORDS):
            return RouteDecision("ppt_generation", "rule", "matched_ppt_keywords", 0.98)

        if self._contains_any(text, SUMMARY_KEYWORDS):
            return RouteDecision("document_summary", "rule", "matched_summary_keywords", 0.98)

        if has_attachments and self._contains_any(text, RAG_HINT_KEYWORDS):
            return RouteDecision("rag_qa", "rule", "attachments_present_with_question", 0.95)

        if has_attachments and not text:
            return RouteDecision("document_summary", "rule", "attachments_without_query", 0.92)

        if has_active_kb and self._contains_any(text, RAG_HINT_KEYWORDS):
            return RouteDecision("rag_qa", "rule", "active_kb_with_question", 0.95)

        if has_active_kb and self._contains_any(text, GENERATION_KEYWORDS):
            return RouteDecision("content_generation", "rule", "active_kb_with_generation_request", 0.92)

        if has_attachments and self._contains_any(text, GENERATION_KEYWORDS):
            return RouteDecision("content_generation", "rule", "attachments_with_generation_request", 0.90)

        if self._contains_any(lower, FALLBACK_KEYWORDS) and not has_attachments and not has_active_kb:
            return RouteDecision("fallback_chat", "rule", "matched_fallback_keywords", 0.95)

        if has_active_kb:
            return RouteDecision("rag_qa", "rule", "active_kb_default", 0.80)

        if has_attachments:
            return RouteDecision("document_summary", "rule", "attachments_default", 0.80)

        if self._contains_any(text, GENERATION_KEYWORDS):
            return RouteDecision("content_generation", "rule", "matched_generation_keywords", 0.88)

        if not self.llm:
            return RouteDecision("fallback_chat", "default", "no_router_model", 0.50)

        return await self._llm_decide(text)

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
            route = self._normalize_route(raw)
            elapsed_ms = int((loop.time() - started) * 1000)
            logger.info(f"[RequestRouter] llm route={route}, elapsed={elapsed_ms}ms, raw={raw[:80]}")
            return RouteDecision(route, "small_llm", f"llm_decision:{raw[:40]}", 0.70)
        except TimeoutError:
            logger.warning("[RequestRouter] LLM route timeout, fallback to fallback_chat")
            return RouteDecision("fallback_chat", "fallback", "router_timeout", 0.40)
        except Exception as exc:
            logger.warning(f"[RequestRouter] LLM route failed: {exc}")
            return RouteDecision("fallback_chat", "fallback", "router_failure", 0.40)

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _normalize_route(raw: str) -> str:
        raw = (raw or "").strip().splitlines()[0].strip()
        allowed = {
            "rag_qa",
            "document_summary",
            "content_generation",
            "pdf_generation",
            "ppt_generation",
            "fallback_chat",
        }
        return raw if raw in allowed else "fallback_chat"

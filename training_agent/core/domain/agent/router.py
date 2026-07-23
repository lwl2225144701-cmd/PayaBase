"""Agent 请求路由领域服务（Request Routing Domain Service）。

职责：
- 路由关键词由调用方（应用层）从配置注入，领域层不依赖 settings，便于测试与热更新。
- 支持**否定词**（negation）：如「不要生成 PDF」不应路由到 pdf_generation。
- 按命中置信度排序而非硬编码固定优先级（PDF>PPT>Summary>...）。

LLM 兜底路由（需要 llm_client + prompt）属于应用/基础设施关注点，
保留在 `core/agent/request_router.py`，由应用层在规则未命中时调用。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RouteDecision:
    route: str
    decision_source: str
    reason: str
    confidence: float


@dataclass
class RoutingKeywordConfig:
    """路由关键词配置（由 core/config.py 注入）。"""

    pdf: tuple[str, ...] = ()
    ppt: tuple[str, ...] = ()
    summary: tuple[str, ...] = ()
    generation: tuple[str, ...] = ()
    rag_hint: tuple[str, ...] = ()
    fallback: tuple[str, ...] = ()
    negation: tuple[str, ...] = ()


ALLOWED_ROUTES = frozenset(
    {
        "rag_qa",
        "document_summary",
        "content_generation",
        "pdf_generation",
        "ppt_generation",
        "fallback_chat",
    }
)


class RequestRoutingService:
    """基于规则的请求路由领域服务。"""

    def __init__(self, keyword_config: RoutingKeywordConfig):
        self.cfg = keyword_config

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(kw in text for kw in keywords)

    def _has_negation(self, text: str) -> bool:
        return self._contains_any(text, self.cfg.negation)

    def decide(
        self,
        *,
        query: str,
        has_attachments: bool,
        has_active_kb: bool,
    ) -> RouteDecision:
        text = (query or "").strip()
        # 否定词：整体抑制「生成类」路由（pdf/ppt/generation）
        negated = self._has_negation(text)

        # 收集候选 (route, confidence, reason)，按置信度降序选取
        candidates: list[tuple[str, float, str]] = []

        if not negated:
            if self._contains_any(text, self.cfg.pdf):
                candidates.append(("pdf_generation", 0.98, "matched_pdf_keywords"))
            if self._contains_any(text, self.cfg.ppt):
                candidates.append(("ppt_generation", 0.98, "matched_ppt_keywords"))
            if self._contains_any(text, self.cfg.summary):
                candidates.append(("document_summary", 0.98, "matched_summary_keywords"))
            if self._contains_any(text, self.cfg.generation):
                candidates.append(("content_generation", 0.92, "matched_generation_keywords"))

        if has_attachments and self._contains_any(text, self.cfg.rag_hint):
            candidates.append(("rag_qa", 0.95, "attachments_present_with_question"))
        if has_attachments and not text:
            candidates.append(("document_summary", 0.92, "attachments_without_query"))
        if has_active_kb and self._contains_any(text, self.cfg.rag_hint):
            candidates.append(("rag_qa", 0.95, "active_kb_with_question"))
        if has_active_kb and self._contains_any(text, self.cfg.generation) and not negated:
            candidates.append(("content_generation", 0.92, "active_kb_with_generation_request"))
        if has_attachments and self._contains_any(text, self.cfg.generation) and not negated:
            candidates.append(("content_generation", 0.90, "attachments_with_generation_request"))

        if candidates:
            # 同置信度保留首个命中（插入顺序即优先级）
            candidates.sort(key=lambda c: c[1], reverse=True)
            route, confidence, reason = candidates[0]
            return RouteDecision(route, "rule", reason, confidence)

        if (
            self._contains_any(text.lower(), self.cfg.fallback)
            and not has_attachments
            and not has_active_kb
        ):
            return RouteDecision("fallback_chat", "rule", "matched_fallback_keywords", 0.95)
        if has_active_kb:
            return RouteDecision("rag_qa", "rule", "active_kb_default", 0.80)
        if has_attachments:
            return RouteDecision("document_summary", "rule", "attachments_default", 0.80)
        return RouteDecision("fallback_chat", "rule", "no_rule_match", 0.60)

    @staticmethod
    def normalize_route(raw: str) -> str:
        raw = (raw or "").strip().splitlines()[0].strip()
        return raw if raw in ALLOWED_ROUTES else "fallback_chat"

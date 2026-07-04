"""Policy guardrails for autonomous agent runs."""

from dataclasses import dataclass
import random


@dataclass
class AgentPolicy:
    max_steps: int = 5
    max_retries: int = 2
    retry_base_delay_sec: float = 0.6
    retry_max_delay_sec: float = 3.0
    allowed_routes: tuple[str, ...] = (
        "rag_qa",
        "document_summary",
        "content_generation",
        "ppt_generation",
        "pdf_generation",
        "fallback_chat",
    )

    def route_allowed(self, route: str) -> bool:
        return route in self.allowed_routes

    def is_retryable_error(self, error: str) -> bool:
        msg = (error or "").lower()
        non_retryable_keywords = (
            "validation",
            "invalid",
            "permission",
            "forbidden",
            "unauthorized",
            "not found",
            "401",
            "403",
            "404",
        )
        return not any(k in msg for k in non_retryable_keywords)

    def retry_backoff_seconds(self, attempt: int) -> float:
        # attempt starts from 1
        exp = self.retry_base_delay_sec * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0, 0.25)
        return min(self.retry_max_delay_sec, exp + jitter)

    def classify_error(self, error: str) -> str:
        msg = (error or "").lower()
        if any(k in msg for k in ("timeout", "timed out")):
            return "timeout"
        if any(k in msg for k in ("rate limit", "too many requests", "429")):
            return "rate_limit"
        if any(k in msg for k in ("401", "unauthorized", "api key", "auth")):
            return "auth"
        if any(k in msg for k in ("403", "forbidden", "permission")):
            return "permission"
        if any(k in msg for k in ("400", "validation", "invalid")):
            return "validation"
        if any(k in msg for k in ("404", "not found")):
            return "not_found"
        if any(k in msg for k in ("500", "502", "503", "504", "service unavailable", "connection")):
            return "upstream"
        return "unknown"

    def fallback_message_for(self, error_type: str) -> str:
        mapping = {
            "timeout": "抱歉，当前处理超时，请稍后重试。",
            "rate_limit": "抱歉，请求较多，请稍后再试。",
            "auth": "抱歉，模型服务认证失败，请联系管理员检查配置。",
            "permission": "抱歉，当前请求权限不足，无法完成。",
            "validation": "抱歉，请求参数不完整或格式不正确，请调整后重试。",
            "not_found": "抱歉，未找到所需资源，请检查后重试。",
            "upstream": "抱歉，模型服务暂时不可用，请稍后重试。",
            "unknown": "抱歉，处理失败，请稍后重试。",
        }
        return mapping.get(error_type, mapping["unknown"])

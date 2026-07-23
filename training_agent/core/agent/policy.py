"""Policy guardrails for autonomous agent runs (应用层)。

错误分类逻辑已下沉到 `core/domain/agent/policy.py`（单一事实来源）：
本类保留运行期配置（max_steps / max_retries / allowed_routes）与
重试退避策略，并把 classify / is_retryable / fallback_message 委托给领域服务。
"""

import random
from dataclasses import dataclass

from core.domain.agent.policy import (
    classify_error,
    fallback_message_for,
    is_retryable_error,
)


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

    # —— 以下三个方法委托给领域层（单一关键词表，避免漂移）——
    def is_retryable_error(self, error: str) -> bool:
        return is_retryable_error(error)

    def classify_error(self, error: str) -> str:
        return classify_error(error)

    def fallback_message_for(self, error_type: str) -> str:
        return fallback_message_for(error_type)

    def retry_backoff_seconds(self, attempt: int) -> float:
        # attempt starts from 1
        exp = self.retry_base_delay_sec * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0, 0.25)
        return min(self.retry_max_delay_sec, exp + jitter)

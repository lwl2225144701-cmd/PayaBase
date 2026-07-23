"""Agent 错误分类领域规则（Error Classification Policy）。

单一事实来源：`classify_error` 维护**唯一**关键词表；`is_retryable_error`
完全基于 `classify_error` 的返回值，杜绝两套关键词表漂移。

原 `core/agent/policy.py` 的 `is_retryable_error` 漏了 "400"，导致
`"400 Bad Request"` 被判定为「可重试」，而 `classify_error` 将其归为
`validation`（`不可重试`）——结论相反。下沉到领域层后，二者永远一致。
"""

from __future__ import annotations

# 不可重试的错误类别
NON_RETRYABLE_CATEGORIES = frozenset({"auth", "permission", "validation", "not_found"})

# 兜底用户提示（按类别映射）
_FALLBACK_MESSAGES: dict[str, str] = {
    "timeout": "抱歉，当前处理超时，请稍后重试。",
    "rate_limit": "抱歉，请求较多，请稍后再试。",
    "auth": "抱歉，模型服务认证失败，请联系管理员检查配置。",
    "permission": "抱歉，当前请求权限不足，无法完成。",
    "validation": "抱歉，请求参数不完整或格式不正确，请调整后重试。",
    "not_found": "抱歉，未找到所需资源，请检查后重试。",
    "upstream": "抱歉，模型服务暂时不可用，请稍后重试。",
    "unknown": "抱歉，处理失败，请稍后重试。",
}


def classify_error(error: str) -> str:
    """将错误信息归类到固定类别（唯一关键词表）。"""
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


def is_retryable_error(error: str) -> bool:
    """基于 classify_error 的返回值判断：auth/permission/validation/not_found 不可重试。"""
    return classify_error(error) not in NON_RETRYABLE_CATEGORIES


def fallback_message_for(error_type: str) -> str:
    """按错误类别返回兜底用户提示。"""
    return _FALLBACK_MESSAGES.get(error_type, _FALLBACK_MESSAGES["unknown"])

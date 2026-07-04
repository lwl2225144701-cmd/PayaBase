"""LLM 工厂:策略模式 + 简单工厂。

业务层调用:
    from core.llm.factory import get_llm_client
    llm = get_llm_client("chat")
    router_llm = get_llm_client("classify")

切换模型:
    - 只改 .env / 配置文件即可,不需要改业务代码
    - 业务层不出现 api_key / base_url / model / provider 判断
"""

import logging
from typing import Optional

from core.config import settings
from core.llm.profiles import (
    LLMProfile,
    PROVIDER_OPENAI,
    PROVIDER_OPENAI_COMPATIBLE,
    PROVIDER_OLLAMA,
    PURPOSE_CHAT,
    PURPOSE_CLASSIFY,
    PURPOSE_DEFAULT,
    PURPOSE_VISION,
    PURPOSES,
)

logger = logging.getLogger(__name__)


# ===== Profile 装配 =====

def _normalize_provider(purpose: str, raw: str) -> str:
    """将配置中的 provider 字符串规范化。

    openai_compatible 等价于 openai,统一在 client 内部走 OpenAI 兼容路径。
    空串表示跟随默认 settings.llm_provider。
    未识别 provider 直接 raise ValueError,避免掩盖线上配置错误。
    """
    if not raw:
        return ""
    p = raw.strip().lower()
    if p == PROVIDER_OPENAI_COMPATIBLE:
        return PROVIDER_OPENAI
    if p in (PROVIDER_OPENAI, PROVIDER_OLLAMA):
        return p
    raise ValueError(
        f"Unsupported LLM provider: {raw!r} (purpose={purpose}). "
        f"Allowed: openai / openai_compatible / ollama"
    )


def get_llm_profile(purpose: str = PURPOSE_DEFAULT) -> LLMProfile:
    """按用途装配 LLMProfile。

    各 purpose 缺省时回退到 settings.llm_* 默认配置(行为与拆分前完全一致)。
    """
    if purpose not in PURPOSES:
        logger.warning(f"[LLM] 未知 purpose={purpose!r}, 回落为 default")
        purpose = PURPOSE_DEFAULT

    s = settings

    # 默认 provider 也需要校验,非法值快速失败
    _default_provider = _normalize_provider("default", s.llm_provider) or PROVIDER_OPENAI

    if purpose == PURPOSE_CLASSIFY:
        provider = _normalize_provider(purpose, s.llm_classify_provider) or _default_provider
        return LLMProfile(
            purpose=purpose,
            provider=provider,
            api_key=s.llm_classify_api_key or s.llm_api_key,
            base_url=s.llm_classify_base_url or s.llm_base_url,
            model=s.llm_classify_model or s.llm_model,
            timeout=float(s.llm_classify_timeout or s.llm_default_timeout),
        )

    if purpose == PURPOSE_CHAT:
        provider = _normalize_provider(purpose, s.llm_chat_provider) or _default_provider
        return LLMProfile(
            purpose=purpose,
            provider=provider,
            api_key=s.llm_chat_api_key or s.llm_api_key,
            base_url=s.llm_chat_base_url or s.llm_base_url,
            model=s.llm_chat_model or s.llm_model,
            timeout=float(s.llm_chat_timeout or s.llm_default_timeout),
            api_header_name=s.llm_chat_api_header_name,
            api_header_prefix=s.llm_chat_api_header_prefix,
        )

    if purpose == PURPOSE_VISION:
        provider = _normalize_provider(purpose, s.llm_vision_provider) or _default_provider
        return LLMProfile(
            purpose=purpose,
            provider=provider,
            api_key=s.llm_vision_api_key or s.llm_api_key,
            base_url=s.llm_vision_base_url or s.llm_base_url,
            # Vision 模型必须显式配置,不 fallback 到 LLM_MODEL,
            # 避免普通文本模型被误用于图片识别。
            model=s.llm_vision_model,
            timeout=float(s.llm_vision_timeout or s.llm_default_timeout),
        )

    # default
    return LLMProfile(
        purpose=PURPOSE_DEFAULT,
        provider=_default_provider,
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        model=s.llm_model,
        timeout=float(s.llm_default_timeout),
    )


# ===== Vision 可用性判断 =====

def is_vision_enabled() -> bool:
    """判断 Vision 模型是否已配置(不创建 LLMClient,仅做配置检查)。

    用于业务层在调用 get_llm_client("vision") 之前判断是否跳过 Vision 功能。
    provider 非法时会 raise ValueError,避免静默错误。
    """
    profile = get_llm_profile(PURPOSE_VISION)
    return bool(profile.model)


# ===== 客户端工厂 =====

# 缓存 key 包含 profile 全部维度 + effective_timeout,避免配置变更后误复用旧 client。
# 生产环境配置变更推荐重启服务;测试或热更新场景可调用 clear_llm_client_cache()。
_CLIENT_CACHE: dict[tuple, object] = {}


def get_llm_client(purpose: str = PURPOSE_DEFAULT, timeout: Optional[float] = None):
    """获取 LLM 客户端(策略模式 + 工厂 + 缓存)。

    Args:
        purpose: classify / chat / vision / default
        timeout: 可选覆盖 profile 中的超时

    Returns:
        LLMClient 实例
    """
    from core.llm.client import LLMClient  # 延迟导入,避免循环

    profile = get_llm_profile(purpose)
    effective_timeout = float(timeout) if timeout is not None else profile.timeout

    cache_key = (
        profile.purpose,
        profile.provider,
        profile.base_url,
        profile.model,
        profile.api_key,
        profile.api_header_name,
        profile.api_header_prefix,
        effective_timeout,
    )
    if cache_key in _CLIENT_CACHE:
        return _CLIENT_CACHE[cache_key]

    client = LLMClient(
        api_key=profile.api_key,
        base_url=profile.base_url,
        model=profile.model,
        provider=profile.provider,
        timeout=effective_timeout,
        api_header_name=profile.api_header_name,
        api_header_prefix=profile.api_header_prefix,
    )
    _CLIENT_CACHE[cache_key] = client
    logger.info(
        f"[LLM] 创建客户端: purpose={profile.purpose}, provider={profile.provider}, "
        f"model={profile.model}, base_url={profile.base_url}"
    )
    return client


def clear_llm_client_cache() -> None:
    """清除缓存(用于测试 / 配置热更新)。"""
    _CLIENT_CACHE.clear()

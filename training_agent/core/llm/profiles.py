"""LLM profile definitions.

按用途(purpose)聚合模型配置,业务层不再关心 provider / api_key / base_url 等细节。
新增模型/切换模型时,只改 .env 与 LLMProfile 装配,不需要改业务代码。
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

# ===== 用途常量 =====
PURPOSE_CLASSIFY = "classify"   # 轻量分类 / 路由
PURPOSE_CHAT = "chat"           # 高质量生成
PURPOSE_VISION = "vision"       # 多模态视觉
PURPOSE_DEFAULT = "default"     # 通用(回退到 LLM_*)

PURPOSES = (PURPOSE_CLASSIFY, PURPOSE_CHAT, PURPOSE_VISION, PURPOSE_DEFAULT)

# ===== Provider 字符串(规范化前) =====
PROVIDER_OPENAI = "openai"                # OpenAI 官方
PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"  # 任意 OpenAI 兼容协议
PROVIDER_OLLAMA = "ollama"                # 本地 Ollama


@dataclass(frozen=True)
class LLMProfile:
    """一个用途对应的完整模型配置。

    业务层只持有 LLMProfile 即可拿到所需一切,不再直接读 settings。
    """
    purpose: str
    provider: str                          # openai / openai_compatible / ollama
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: float = 30.0
    api_header_name: str = ""              # 自定义鉴权头(例如部分网关要求)
    api_header_prefix: str = "Bearer "     # 鉴权前缀

    def supports_vision(self) -> bool:
        """是否支持视觉(本地 Ollama 通常不支持,留作上层判断)。"""
        return self.provider != PROVIDER_OLLAMA

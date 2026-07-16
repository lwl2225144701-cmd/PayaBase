"""Prompt Templates.

Centralized prompt management for the training agent.
"""

from core.prompts.chat import (
    build_attachment_only_prompt,
    build_attachment_with_kb_prompt,
    build_kb_only_prompt,
    FALLBACK_PROMPT,
)
from core.prompts.indexing import (
    HYDE_QUERY_SYSTEM_PROMPT,
    HYDE_QUERY_USER_PROMPT,
)
from core.prompts.vision import VISION_PROMPT
from core.prompts.agent import (
    AGENT_SYSTEM_PROMPT,
    CASUAL_CHAT_PROMPT,
    INTENT_SYSTEM_PROMPT,
    ROUTER_CLASSIFY_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    ROUTER_FALLBACK_PROMPT,
    build_rag_prompt,
    build_intent_prompt,
)

__all__ = [
    # Chat
    "build_attachment_only_prompt",
    "build_attachment_with_kb_prompt",
    "build_kb_only_prompt",
    "FALLBACK_PROMPT",
    # Retrieval (查询时 HyDE)
    "HYDE_QUERY_SYSTEM_PROMPT",
    "HYDE_QUERY_USER_PROMPT",
    # Vision
    "VISION_PROMPT",
    # Agent
    "AGENT_SYSTEM_PROMPT",
    "CASUAL_CHAT_PROMPT",
    "INTENT_SYSTEM_PROMPT",
    "ROUTER_CLASSIFY_PROMPT",
    "ROUTER_SYSTEM_PROMPT",
    "ROUTER_FALLBACK_PROMPT",
    "build_rag_prompt",
    "build_intent_prompt",
]

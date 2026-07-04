"""Prompt Templates.

Re-exports from centralized core.prompts.agent.
"""

from core.prompts.agent import (
    AGENT_SYSTEM_PROMPT as SYSTEM_PROMPT,
    CASUAL_CHAT_PROMPT,
    build_rag_prompt,
    build_intent_prompt,
)

__all__ = [
    "SYSTEM_PROMPT",
    "CASUAL_CHAT_PROMPT",
    "build_rag_prompt",
    "build_intent_prompt",
]

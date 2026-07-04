from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request


@dataclass
class PlatformMessage:
    """Unified incoming message model across platforms."""

    platform: str
    platform_message_id: str
    user_id: str
    conversation_id: str
    content: str
    timestamp: int
    attachments: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PlatformAdapter(ABC):
    """Abstract adapter contract for external chat platforms."""

    @property
    @abstractmethod
    def platform(self) -> str:
        pass

    @abstractmethod
    async def parse_message(self, raw_data: dict[str, Any]) -> PlatformMessage:
        pass

    @abstractmethod
    async def verify_signature(self, request: Request) -> bool:
        pass

    @abstractmethod
    async def send_response(self, conversation_id: str, content: str, **kwargs) -> None:
        pass

    @abstractmethod
    async def get_user_info(self, platform_user_id: str) -> dict[str, Any]:
        pass

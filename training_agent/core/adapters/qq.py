from __future__ import annotations

import time
from typing import Any

from fastapi import Request

from core.adapters.base import PlatformAdapter, PlatformMessage


class QQAdapter(PlatformAdapter):
    @property
    def platform(self) -> str:
        return "qq"

    async def verify_signature(self, request: Request) -> bool:
        # Placeholder: implement QQ bot signature verification in production.
        return True

    async def parse_message(self, raw_data: dict[str, Any]) -> PlatformMessage:
        return PlatformMessage(
            platform=self.platform,
            platform_message_id=str(raw_data.get("message_id") or raw_data.get("id") or ""),
            user_id=str(raw_data.get("user_id") or ""),
            conversation_id=str(raw_data.get("group_id") or raw_data.get("channel_id") or raw_data.get("conversation_id") or ""),
            content=str(raw_data.get("content") or "").strip(),
            timestamp=int(raw_data.get("timestamp") or time.time()),
            metadata=raw_data,
        )

    async def send_response(self, conversation_id: str, content: str, **kwargs) -> None:
        return None

    async def get_user_info(self, platform_user_id: str) -> dict[str, Any]:
        return {}

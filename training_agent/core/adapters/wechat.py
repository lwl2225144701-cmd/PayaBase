from __future__ import annotations

import time
from typing import Any

from fastapi import Request

from core.adapters.base import PlatformAdapter, PlatformMessage


class WechatAdapter(PlatformAdapter):
    @property
    def platform(self) -> str:
        return "wechat"

    async def verify_signature(self, request: Request) -> bool:
        # Placeholder: implement WeChat signature algorithm in production.
        return True

    async def parse_message(self, raw_data: dict[str, Any]) -> PlatformMessage:
        return PlatformMessage(
            platform=self.platform,
            platform_message_id=str(raw_data.get("message_id") or raw_data.get("MsgId") or ""),
            user_id=str(raw_data.get("from_user") or raw_data.get("FromUserName") or ""),
            conversation_id=str(raw_data.get("conversation_id") or raw_data.get("ToUserName") or ""),
            content=str(raw_data.get("content") or raw_data.get("Content") or "").strip(),
            timestamp=int(raw_data.get("timestamp") or raw_data.get("CreateTime") or time.time()),
            metadata=raw_data,
        )

    async def send_response(self, conversation_id: str, content: str, **kwargs) -> None:
        return None

    async def get_user_info(self, platform_user_id: str) -> dict[str, Any]:
        return {}

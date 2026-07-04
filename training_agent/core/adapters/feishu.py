from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from fastapi import Request

from core.adapters.base import PlatformAdapter, PlatformMessage
from core.config import settings

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuAdapter(PlatformAdapter):
    @property
    def platform(self) -> str:
        return "feishu"

    async def verify_signature(self, request: Request) -> bool:
        # Keep permissive when secret isn't configured.
        secret = settings.feishu_verification_token
        if not secret:
            return True

        timestamp = request.headers.get("x-lark-request-timestamp") or request.headers.get("x-feishu-signature-timestamp")
        signature = request.headers.get("x-lark-signature") or request.headers.get("x-feishu-signature")
        if not timestamp or not signature:
            return False

        body = await request.body()
        # Lark event signature canonical string: timestamp + nonce + body (nonce may be absent in headers for some modes)
        nonce = request.headers.get("x-lark-request-nonce", "")
        sign_content = f"{timestamp}{nonce}{body.decode('utf-8')}"
        expected = hmac.new(secret.encode("utf-8"), sign_content.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    async def parse_message(self, raw_data: dict[str, Any]) -> PlatformMessage:
        event = raw_data.get("event", {}) or {}
        message = event.get("message", {}) or {}
        sender = event.get("sender", {}) or {}

        content = ""
        try:
            content_json = json.loads(message.get("content", "{}"))
            content = content_json.get("text", "") or ""
        except Exception:
            content = ""

        create_time_ms = int(message.get("create_time") or int(time.time() * 1000))
        sender_id_obj = sender.get("sender_id", {}) or {}
        platform_user_id = sender_id_obj.get("open_id") or sender_id_obj.get("user_id") or ""

        return PlatformMessage(
            platform=self.platform,
            platform_message_id=message.get("message_id", ""),
            user_id=platform_user_id,
            conversation_id=message.get("chat_id", ""),
            content=content.strip(),
            timestamp=create_time_ms // 1000,
            metadata={
                "chat_type": message.get("chat_type"),
                "message_type": message.get("message_type"),
                "tenant_key": (raw_data.get("header") or {}).get("tenant_key"),
            },
        )

    async def send_response(self, conversation_id: str, content: str, **kwargs) -> None:
        token = await self._get_tenant_access_token()
        body = {
            "receive_id": conversation_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}, ensure_ascii=False),
        }
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{FEISHU_API_BASE}/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}"},
                json=body,
                timeout=20.0,
            )

    async def get_user_info(self, platform_user_id: str) -> dict[str, Any]:
        token = await self._get_tenant_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{FEISHU_API_BASE}/contact/v3/users/{platform_user_id}",
                params={"user_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20.0,
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
            if data.get("code") != 0:
                return {}
            user = data.get("data", {}).get("user", {}) or {}
            return {
                "display_name": user.get("name") or user.get("en_name") or "",
                "email": user.get("email") or "",
            }

    async def _get_tenant_access_token(self) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
                timeout=15.0,
            )
            data = resp.json()
            return data.get("tenant_access_token", "")

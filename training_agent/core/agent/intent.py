"""Intent classifier.

User intent recognition + knowledge base routing.
With timeout control and Redis caching (10min TTL).
"""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Optional

import redis

from core.llm.client import LLMClient
from core.config import settings
from core.prompts.agent import INTENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Thread pool for timeout control
_executor = ThreadPoolExecutor(max_workers=2)

CACHE_TTL = 600  # 10 minutes

# Redis client (sync, used inside thread executor)
_redis = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=2,  # use db=2 for intent cache (0=celery, 1=celery result)
    decode_responses=True,
)

CACHE_PREFIX = "intent:"


def _cache_key(query: str, kb_list: list[dict] | None = None) -> str:
    """Build cache key from query + kb_list fingerprint."""
    q = query.strip().lower()
    # Include kb_list hash so cache invalidates when KBs change
    kb_hash = ""
    if kb_list:
        kb_hash = hashlib.md5(
            json.dumps([kb["name"] for kb in kb_list], ensure_ascii=False).encode()
        ).hexdigest()[:8]
    return f"{CACHE_PREFIX}{kb_hash}:{hashlib.md5(q.encode()).hexdigest()[:16]}"


class IntentClassifier:
    """User intent classifier with KB routing."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    def classify(self, query: str, kb_list: list[dict] | None = None) -> dict:
        """Classify query intent and optionally route to a knowledge base.

        Args:
            query: User query
            kb_list: [{"index": 1, "name": "xxx", "description": "xxx"}, ...]

        Returns:
            {"intent": "knowledge_query"|"casual_chat", "kb_index": int|None}
        """
        key = _cache_key(query, kb_list)

        # 1. Check Redis cache
        try:
            cached = _redis.get(key)
            if cached:
                logger.info(f"[IntentClassifier] Redis缓存命中: {query[:30]}")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"[IntentClassifier] Redis读取失败: {e}")

        # 2. No LLM -> fallback
        if not self.llm:
            return {"intent": "knowledge_query", "kb_index": None}

        # 3. Format prompt
        if kb_list:
            kb_text = "\n".join(
                [f"{kb['index']}. {kb['name']} — {kb['description']}" for kb in kb_list]
            )
        else:
            kb_text = "（无可用知识库）"

        system_prompt = INTENT_SYSTEM_PROMPT.format(kb_list=kb_text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户：{query}"},
        ]

        # 4. Call LLM with timeout
        try:
            t0 = time.time()
            future = _executor.submit(self.llm.chat, messages, 0)
            timeout = settings.llm_classify_timeout
            raw = future.result(timeout=timeout)
            elapsed = (time.time() - t0) * 1000
            logger.info(f"[Timing] IntentClassifier LLM调用: {elapsed:.0f}ms, model={self.llm.model}")
            raw = (raw or "").strip()
            logger.info(f"[Timing] IntentClassifier 响应: {raw[:200]}")

            result = self._parse_json(raw)

        except FuturesTimeoutError:
            logger.warning(f"[IntentClassifier] LLM调用超时({settings.llm_classify_timeout}s), fallback")
            result = {"intent": "knowledge_query", "kb_index": None}
        except Exception as e:
            logger.warning(f"[IntentClassifier] 分类失败: {e}")
            result = {"intent": "knowledge_query", "kb_index": None}

        # 5. Write to Redis cache
        try:
            _redis.setex(key, CACHE_TTL, json.dumps(result, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"[IntentClassifier] Redis写入失败: {e}")

        return result

    def _parse_json(self, raw: str) -> dict:
        """Parse JSON response from LLM."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[^}]+\}', text)
            if match:
                data = json.loads(match.group())
            else:
                logger.warning(f"[IntentClassifier] JSON解析失败: {raw[:100]}")
                return {"intent": "knowledge_query", "kb_index": None}

        intent = data.get("intent", "knowledge_query")
        kb_index = data.get("kb_index")

        if intent not in ("knowledge_query", "solution_query", "casual_chat"):
            intent = "knowledge_query"

        if kb_index is not None:
            try:
                kb_index = int(kb_index)
            except (ValueError, TypeError):
                kb_index = None

        # kb_index must be 1-based; 0 means model didn't follow instructions
        if kb_index is not None and kb_index < 1:
            kb_index = None

        return {"intent": intent, "kb_index": kb_index}

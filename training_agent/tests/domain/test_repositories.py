"""Repository 端口契约测试 + Fake 实现。

验证：
1. Fake 实现满足 Protocol 端口（结构子类型，运行时可调用全部方法）
2. CRUD 行为正确（save/get/list/delete）
3. ChunkRepository.batch_replace 幂等（不叠加）
4. ConversationRepository 租户/用户隔离
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.domain.conversation.repository import ConversationRepository, MessageRepository
from core.domain.knowledge_base.repository import ChunkRepository


# ---------------------------------------------------------------------------
# Fake 实现（内存 dict，不连库；结构上满足 Protocol 端口）
# ---------------------------------------------------------------------------


class FakeConversationRepository:
    """ConversationRepository 端口的内存 Fake。"""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, conv_id, tenant_id, user_id):
        c = self._store.get(conv_id)
        if c and c.tenant_id == tenant_id and c.user_id == user_id:
            return c
        return None

    async def list_by_user(self, tenant_id, user_id, page=1, page_size=20):
        items = [
            c for c in self._store.values()
            if c.tenant_id == tenant_id and c.user_id == user_id
        ]
        items.sort(key=lambda c: c.created_at, reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total

    async def save(self, conv):
        self._store[conv.id] = conv
        return conv

    async def delete(self, conv_id, tenant_id, user_id):
        c = self._store.get(conv_id)
        if c and c.tenant_id == tenant_id and c.user_id == user_id:
            del self._store[conv_id]
            return True
        return False


class FakeChunkRepository:
    """ChunkRepository 端口的内存 Fake（含 batch_replace 幂等语义）。"""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, list[Any]] = {}

    async def get_by_document(self, document_id):
        return list(self._store.get(document_id, []))

    async def batch_replace(self, document_id, chunks):
        self._store[document_id] = list(chunks)
        return len(chunks)

    async def delete_by_document(self, document_id):
        n = len(self._store.get(document_id, []))
        self._store[document_id] = []
        return n

    async def hybrid_search(self, kb_id, query_vector, query_text="", top_k=10, filters=None):
        raise NotImplementedError


def _make_conversation(tenant_id, user_id, title="test"):
    """构造内存会话对象（模拟 ORM，不连库）。"""
    conv = MagicMock()
    conv.id = uuid.uuid4()
    conv.tenant_id = tenant_id
    conv.user_id = user_id
    conv.title = title
    conv.created_at = uuid.uuid4().time  # 用 uuid 时间戳模拟排序
    return conv


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


class TestFakeConversationRepository:
    """验证 Fake 满足 ConversationRepository 端口 + CRUD 行为。"""

    def test_satisfies_protocol(self):
        """Fake 实现拥有端口全部方法（Protocol 结构子类型）。"""
        fake = FakeConversationRepository()
        for method in ("get_by_id", "list_by_user", "save", "delete"):
            assert hasattr(fake, method), f"Fake 缺少端口方法: {method}"

    @pytest.mark.asyncio
    async def test_save_and_get(self):
        repo = FakeConversationRepository()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        conv = _make_conversation(tenant_id, user_id)

        await repo.save(conv)
        got = await repo.get_by_id(conv.id, tenant_id, user_id)
        assert got is conv

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        """其他租户的用户无法获取会话。"""
        repo = FakeConversationRepository()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        user_a = uuid.uuid4()
        conv = _make_conversation(tenant_a, user_a)
        await repo.save(conv)

        # 租户 B 的用户看不到租户 A 的会话
        assert await repo.get_by_id(conv.id, tenant_b, user_a) is None

    @pytest.mark.asyncio
    async def test_list_pagination(self):
        repo = FakeConversationRepository()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        for i in range(5):
            await repo.save(_make_conversation(tenant_id, user_id, title=f"conv-{i}"))

        items, total = await repo.list_by_user(tenant_id, user_id, page=1, page_size=3)
        assert total == 5
        assert len(items) == 3

        items2, total2 = await repo.list_by_user(tenant_id, user_id, page=2, page_size=3)
        assert total2 == 5
        assert len(items2) == 2

    @pytest.mark.asyncio
    async def test_delete_with_isolation(self):
        repo = FakeConversationRepository()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        conv = _make_conversation(tenant_id, user_id)
        await repo.save(conv)

        # 其他用户删不了
        assert await repo.delete(conv.id, tenant_id, uuid.uuid4()) is False
        assert await repo.get_by_id(conv.id, tenant_id, user_id) is not None

        # 本人可删
        assert await repo.delete(conv.id, tenant_id, user_id) is True
        assert await repo.get_by_id(conv.id, tenant_id, user_id) is None


class TestFakeChunkRepository:
    """验证 ChunkRepository.batch_replace 幂等（不叠加）。"""

    @pytest.mark.asyncio
    async def test_batch_replace_idempotent(self):
        """连续两次 batch_replace，chunk 数量不翻倍。"""
        repo = FakeChunkRepository()
        doc_id = uuid.uuid4()

        chunks_1 = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
        n1 = await repo.batch_replace(doc_id, chunks_1)
        assert n1 == 3
        assert len(await repo.get_by_document(doc_id)) == 3

        # 第二次替换（不同内容），数量应为新数量，不是 3+2=5
        chunks_2 = [{"content": "x"}, {"content": "y"}]
        n2 = await repo.batch_replace(doc_id, chunks_2)
        assert n2 == 2
        stored = await repo.get_by_document(doc_id)
        assert len(stored) == 2  # 幂等：不叠加

    @pytest.mark.asyncio
    async def test_delete_by_document(self):
        repo = FakeChunkRepository()
        doc_id = uuid.uuid4()
        await repo.batch_replace(doc_id, [{"content": "a"}, {"content": "b"}])

        deleted = await repo.delete_by_document(doc_id)
        assert deleted == 2
        assert len(await repo.get_by_document(doc_id)) == 0

"""UnitOfWork：统一事务边界。

取代散落全仓的 db.commit()。Repository 只 add/flush/execute，不 commit；
由 UoW 在用例结束时统一 commit / 异常时 rollback。

用法（应用用例）::

    async with UnitOfWork(session) as uow:
        conv = await uow.conversations.get_by_id(...)
        await uow.messages.save(Message(...))
        # 退出 with 块时自动 commit（异常自动 rollback）

Web 侧沿用每请求 AsyncSession；跨聚合操作由 UoW 统一提交。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.infrastructure.db.repositories import (
    AgentRunRepositoryImpl,
    ChunkRepositoryImpl,
    ConversationRepositoryImpl,
    DocumentRepositoryImpl,
    KnowledgeBaseRepositoryImpl,
    MessageRepositoryImpl,
)


class UnitOfWork:
    """工作单元：聚合各 Repository，统一事务提交/回滚。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.knowledge_bases: KnowledgeBaseRepositoryImpl = KnowledgeBaseRepositoryImpl(session)
        self.documents: DocumentRepositoryImpl = DocumentRepositoryImpl(session)
        self.chunks: ChunkRepositoryImpl = ChunkRepositoryImpl(session)
        self.conversations: ConversationRepositoryImpl = ConversationRepositoryImpl(session)
        self.messages: MessageRepositoryImpl = MessageRepositoryImpl(session)
        self.agent_runs: AgentRunRepositoryImpl = AgentRunRepositoryImpl(session)

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

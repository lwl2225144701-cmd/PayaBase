"""Knowledge Base Service.

Provides business logic for knowledge base operations.
"""

import uuid
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.tables import KnowledgeBase, Document
from core.exceptions import NotFoundException


class KnowledgeBaseService:
    """Service for knowledge base operations."""

    def __init__(self, db: AsyncSession):
        """Initialize service.

        Args:
            db: Database session
        """
        self.db = db

    async def list_knowledge_bases(
        self,
        tenant_id: uuid.UUID,
        department_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[KnowledgeBase], int]:
        """List knowledge bases for a tenant.

        Args:
            tenant_id: Tenant ID
            department_id: Optional department filter
            page: Page number
            page_size: Page size

        Returns:
            Tuple of (knowledge bases, total count)
        """
        query = select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id)
        if department_id:
            query = query.where(KnowledgeBase.department_id == department_id)
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        kb_list = result.scalars().all()

        count_query = select(func.count()).select_from(KnowledgeBase).where(
            KnowledgeBase.tenant_id == tenant_id
        )
        total = await self.db.scalar(count_query) or 0

        return list(kb_list), total

    async def get_knowledge_base(
        self,
        kb_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Optional[KnowledgeBase]:
        """Get knowledge base by ID.

        Args:
            kb_id: Knowledge base ID
            tenant_id: Tenant ID

        Returns:
            Knowledge base or None
        """
        result = await self.db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_knowledge_base(
        self,
        tenant_id: uuid.UUID,
        name: str,
        description: Optional[str] = None,
        department_id: Optional[uuid.UUID] = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> KnowledgeBase:
        """Create new knowledge base.

        Args:
            tenant_id: Tenant ID
            name: Knowledge base name
            description: Optional description
            department_id: Optional department ID
            embedding_model: Embedding model name

        Returns:
            Created knowledge base
        """
        kb = KnowledgeBase(
            tenant_id=tenant_id,
            department_id=department_id,
            name=name,
            description=description,
            embedding_model=embedding_model,
        )
        self.db.add(kb)
        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def update_knowledge_base(
        self,
        kb_id: uuid.UUID,
        tenant_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> KnowledgeBase:
        """Update knowledge base.

        Args:
            kb_id: Knowledge base ID
            tenant_id: Tenant ID
            name: New name
            description: New description

        Returns:
            Updated knowledge base
        """
        result = await self.db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
        kb = result.scalar_one_or_none()
        if not kb:
            raise NotFoundException("Knowledge base not found")

        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description

        await self.db.commit()
        await self.db.refresh(kb)
        return kb

    async def delete_knowledge_base(
        self,
        kb_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """Delete knowledge base.

        Args:
            kb_id: Knowledge base ID
            tenant_id: Tenant ID
        """
        result = await self.db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
        kb = result.scalar_one_or_none()
        if not kb:
            raise NotFoundException("Knowledge base not found")

        await self.db.delete(kb)
        await self.db.commit()
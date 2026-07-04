"""Document Service.

Provides business logic for document operations.
"""

import uuid
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.tables import Document, KnowledgeBase, Chunk
from core.exceptions import NotFoundException


class DocumentService:
    """Service for document operations."""

    def __init__(self, db: AsyncSession):
        """Initialize service.

        Args:
            db: Database session
        """
        self.db = db

    async def list_documents(
        self,
        kb_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Document], int]:
        """List documents for a knowledge base.

        Args:
            kb_id: Knowledge base ID
            page: Page number
            page_size: Page size

        Returns:
            Tuple of (documents, total count)
        """
        query = (
            select(Document)
            .where(Document.knowledge_base_id == kb_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        docs = result.scalars().all()

        count_query = select(func.count()).select_from(Document).where(
            Document.knowledge_base_id == kb_id
        )
        total = await self.db.scalar(count_query) or 0

        return list(docs), total

    async def get_document(self, doc_id: uuid.UUID) -> Optional[Document]:
        """Get document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document or None
        """
        result = await self.db.execute(
            select(Document).where(Document.id == doc_id)
        )
        return result.scalar_one_or_none()

    async def create_document(
        self,
        kb_id: uuid.UUID,
        title: str,
        file_path: str,
        file_type: str,
        file_size: int,
        source_type: str = "local",
        source_url: Optional[str] = None,
    ) -> Document:
        """Create new document.

        Args:
            kb_id: Knowledge base ID
            title: Document title
            file_path: File path in storage
            file_type: File type (e.g., pdf)
            file_size: File size in bytes
            source_type: Source type (local, feishu, google_drive)
            source_url: Original document URL from external source

        Returns:
            Created document
        """
        doc = Document(
            knowledge_base_id=kb_id,
            title=title,
            file_path=file_path,
            file_type=file_type,
            file_size=file_size,
            source_type=source_type,
            source_url=source_url,
            status="pending",
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def update_document_status(
        self,
        doc_id: uuid.UUID,
        status: str,
    ) -> Document:
        """Update document status.

        Args:
            doc_id: Document ID
            status: New status

        Returns:
            Updated document
        """
        result = await self.db.execute(
            select(Document).where(Document.id == doc_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise NotFoundException("Document not found")

        doc.status = status
        if status == "ready":
            from datetime import datetime
            doc.indexed_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def delete_document(self, doc_id: uuid.UUID) -> None:
        """Delete document.

        Args:
            doc_id: Document ID
        """
        result = await self.db.execute(
            select(Document).where(Document.id == doc_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise NotFoundException("Document not found")

        await self.db.delete(doc)
        await self.db.commit()

    async def create_chunks(
        self,
        doc_id: uuid.UUID,
        chunks_data: list[dict],
    ) -> list[Chunk]:
        """Create text chunks for document.

        Args:
            doc_id: Document ID
            chunks_data: List of chunk data dicts

        Returns:
            Created chunks
        """
        chunks = []
        for item in chunks_data:
            chunk = Chunk(
                document_id=doc_id,
                content=item.get("content", ""),
                vector=item.get("vector"),
                meta=item.get("meta", {}),
                token_count=item.get("token_count", 0),
            )
            chunks.append(chunk)
            self.db.add(chunk)

        await self.db.commit()
        return chunks
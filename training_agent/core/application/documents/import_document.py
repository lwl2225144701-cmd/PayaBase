"""文档导入应用用例。

将文档上传/外部源导入/重索引/删除的编排逻辑从 HTTP 路由层下沉到应用层。
router 只保留 HTTP 适配（参数声明、文件读取）与响应组装。

消除重复：import_from_source 原内联 MinIO 上传，现统一复用 _persist。
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.domain.knowledge_base.aggregates import Document as DomainDocument
from core.exceptions import NotFoundException, ValidationException
from core.infrastructure.minio.client import get_minio_client
from core.permissions import require_manage_kb
from models.tables import Document

if TYPE_CHECKING:
    from core.domain.identity.user_info import UserInfo

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_TYPES = [
    "pdf", "doc", "docx", "txt", "md",
    "xlsx", "xls",
    "png", "jpg", "jpeg", "gif", "webp", "bmp",
]


@dataclass(frozen=True)
class DocumentImportResult:
    """文档导入结果（用例返回，router 据此组装响应）。"""

    document: Document
    message: str
    status_override: str | None = None


class ImportDocumentUseCase:
    """文档导入应用用例：编排校验/存储/落库/索引任务。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def upload_document(
        self,
        *,
        kb_id: str,
        filename: str,
        content: bytes,
        file_type: str,
        current_user: UserInfo,
    ) -> DocumentImportResult:
        """上传本地文档：权限 -> 校验 -> 幂等 -> 持久化 -> 触发索引。"""
        await require_manage_kb(self._db, current_user, uuid.UUID(kb_id))

        existing = await self._find_by_hash(kb_id, content)
        if existing is not None:
            hit = self._idempotent_result(existing)
            if hit is not None:
                return hit

        doc = await self._persist(
            kb_id=kb_id,
            title=filename,
            storage_filename=filename,
            file_content=content,
            file_type=file_type,
            source_type="local",
            source_url=None,
        )
        return DocumentImportResult(document=doc, message="文档上传成功，已加入索引队列")

    async def import_from_source(
        self,
        *,
        kb_id: str,
        source_type: str,
        url: str,
        title: str | None,
        current_user: UserInfo,
    ) -> DocumentImportResult:
        """从外部源（飞书/Google Drive）导入文档。"""
        from core.sources.registry import get_source

        await require_manage_kb(self._db, current_user, uuid.UUID(kb_id))

        source = get_source(source_type)
        try:
            result = await source.fetch(url, title=title)
        except Exception as e:
            raise ValidationException(f"从 {source_type} 获取文档失败: {str(e)}") from e

        # 类型/大小校验（与 _persist 一致，提前失败避免无谓幂等查库）
        if result.file_type not in ALLOWED_TYPES:
            raise ValidationException(
                f"不支持的文件类型: {result.file_type}, 支持类型: {', '.join(ALLOWED_TYPES)}"
            )
        if result.content_length > MAX_FILE_SIZE:
            raise ValidationException(
                f"文件过大: {result.content_length / 1024 / 1024:.1f}MB, 最大支持100MB"
            )

        filename = result.filename or f"{source_type}_{uuid.uuid4()}.{result.file_type}"
        return await self.persist_fetched_document(
            kb_id=kb_id,
            current_user=current_user,
            content=result.content,
            filename=filename,
            file_type=result.file_type,
            source_type=result.source_type,
            source_url=result.source_url,
        )

    async def persist_fetched_document(
        self,
        *,
        kb_id: str,
        current_user: UserInfo,
        content: bytes,
        filename: str,
        file_type: str,
        source_type: str,
        source_url: str | None,
    ) -> DocumentImportResult:
        """持久化已拉取的文档（幂等 -> 存储 -> 落库 -> 索引）。

        供 sources.py 的 upload_to_kb 等"自行 fetch"场景复用。
        权限校验由调用方负责。
        """
        existing = await self._find_by_hash(kb_id, content)
        if existing is not None:
            hit = self._idempotent_result(existing)
            if hit is not None:
                return hit

        doc = await self._persist(
            kb_id=kb_id,
            title=filename,
            storage_filename=filename,
            file_content=content,
            file_type=file_type,
            source_type=source_type,
            source_url=source_url,
        )
        return DocumentImportResult(
            document=doc, message=f"文档已从 {source_type} 导入，正在索引"
        )

    async def reindex_document(
        self, *, kb_id: str, doc_id: str, current_user: UserInfo
    ) -> None:
        """重置文档状态并重新触发索引。"""
        await require_manage_kb(self._db, current_user, uuid.UUID(kb_id))
        doc = await self._get_document(kb_id, doc_id)

        doc.status = "pending"
        doc.progress = 0
        doc.error_message = None
        await self._db.commit()

        try:
            from core.tasks.indexing import index_document_task
            task = index_document_task.delay(str(doc.id))
            logger.info(f"Reindex Celery task: {task.id}")
        except Exception as e:
            logger.error(f"Celery任务提交失败: {doc.id}, error={e}")
            raise ValidationException(f"索引任务启动失败: {str(e)}") from e

    async def delete_document(
        self, *, kb_id: str, doc_id: str, current_user: UserInfo
    ) -> None:
        """删除文档：MinIO 对象 + DB 记录。"""
        await require_manage_kb(self._db, current_user, uuid.UUID(kb_id))
        doc = await self._get_document(kb_id, doc_id)

        with contextlib.suppress(Exception):
            get_minio_client().remove_object(settings.minio_bucket, doc.file_path)

        await self._db.delete(doc)
        await self._db.commit()

    # ------------------------------------------------------------------
    # 内部编排
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        kb_id: str,
        title: str,
        storage_filename: str,
        file_content: bytes,
        file_type: str,
        source_type: str = "local",
        source_url: str | None = None,
    ) -> Document:
        """持久化文档：校验 -> MinIO 上传 -> DB 写入 -> Celery 触发 -> 失败补偿。"""
        if file_type not in ALLOWED_TYPES:
            raise ValidationException(
                f"不支持的文件类型: {file_type}, 支持类型: {', '.join(ALLOWED_TYPES)}"
            )
        file_size = len(file_content)
        if file_size > MAX_FILE_SIZE:
            raise ValidationException(
                f"文件过大: {file_size/1024/1024:.1f}MB, 最大支持: {MAX_FILE_SIZE/1024/1024:.0f}MB"
            )

        doc_id = uuid.uuid4()
        file_path = f"{kb_id}/{doc_id}/{storage_filename}"

        try:
            await asyncio.to_thread(self._upload_to_minio, file_path, file_content)
        except Exception as exc:
            logger.error(f"MinIO上传失败: {exc}")
            raise ValidationException(f"文件上传失败: {str(exc)}") from exc

        doc = Document(
            id=doc_id,
            knowledge_base_id=uuid.UUID(kb_id),
            title=title or storage_filename,
            file_path=file_path,
            file_type=file_type,
            file_size=file_size,
            file_hash=hashlib.md5(file_content).hexdigest(),
            source_type=source_type,
            source_url=source_url,
            status="pending",
            progress=0,
        )
        self._db.add(doc)
        try:
            await self._db.commit()
        except Exception as exc:
            await self._db.rollback()
            self._remove_minio_object_safely(file_path)
            logger.error(f"Document记录创建失败: {exc}")
            raise ValidationException(f"文档记录创建失败: {str(exc)}") from exc
        await self._db.refresh(doc)

        try:
            from core.tasks.indexing import index_document_task
            task = index_document_task.delay(str(doc.id))
            logger.info(
                f"Celery任务已提交: doc_id={doc.id}, task_id={task.id}, source={source_type}"
            )
        except Exception as exc:
            logger.error(f"Celery任务提交失败: {doc.id}, error={exc}")
            self._remove_minio_object_safely(file_path)
            await self._delete_document_safely(doc)
            raise ValidationException(f"索引任务提交失败: {str(exc)}") from exc

        return doc

    async def _find_by_hash(self, kb_id: str, content: bytes) -> Document | None:
        file_hash = hashlib.md5(content).hexdigest()
        result = await self._db.execute(
            select(Document).where(
                Document.knowledge_base_id == uuid.UUID(kb_id),
                Document.file_hash == file_hash,
            )
        )
        return result.scalar_one_or_none()

    async def _get_document(self, kb_id: str, doc_id: str) -> Document:
        result = await self._db.execute(
            select(Document).where(
                Document.id == uuid.UUID(doc_id),
                Document.knowledge_base_id == uuid.UUID(kb_id),
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise NotFoundException("Document not found")
        return doc

    def _idempotent_result(self, existing: Document) -> DocumentImportResult | None:
        """幂等命中时返回结果；error 等状态返回 None 表示继续 persist（允许重试）。"""
        doc = DomainDocument.from_orm(existing)
        if doc.is_indexed():
            return DocumentImportResult(
                document=existing,
                message="文档已存在且已索引完成",
                status_override="already_indexed",
            )
        if doc.is_indexing():
            return DocumentImportResult(document=existing, message="文档已在索引中")
        return None

    @staticmethod
    def _upload_to_minio(file_path: str, file_content: bytes) -> None:
        minio_client = get_minio_client()
        if not minio_client.bucket_exists(settings.minio_bucket):
            minio_client.make_bucket(settings.minio_bucket)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(file_content)
            minio_client.fput_object(settings.minio_bucket, file_path, tmp_path)
        finally:
            if tmp_path:
                try:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _remove_minio_object_safely(object_path: str) -> None:
        try:
            get_minio_client().remove_object(settings.minio_bucket, object_path)
        except Exception as exc:
            logger.warning(f"MinIO对象清理失败: path={object_path}, error={exc}")

    async def _delete_document_safely(self, doc: Document) -> None:
        try:
            await self._db.delete(doc)
            await self._db.commit()
        except Exception as exc:
            await self._db.rollback()
            logger.warning(f"Document记录清理失败: doc_id={doc.id}, error={exc}")

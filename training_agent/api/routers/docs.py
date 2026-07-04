import hashlib
import uuid
import logging
import asyncio

from fastapi import APIRouter, File, UploadFile
from sqlalchemy import select
from typing import Optional

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response
from api.schemas.doc import DocumentResponse, DocumentListResponse, DocumentFromSourceRequest
from core.config import settings
from core.exceptions import NotFoundException, ValidationException
from core.permissions import require_manage_kb, require_visible_kb
from models.tables import Document, Chunk
from minio import Minio

logger = logging.getLogger(__name__)

router = APIRouter()


def get_minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )


def _upload_bytes_to_minio(file_path: str, file_content: bytes) -> None:
    minio_client = get_minio_client()
    if not minio_client.bucket_exists(settings.minio_bucket):
        minio_client.make_bucket(settings.minio_bucket)

    import tempfile
    import os

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


def _remove_minio_object_safely(object_path: str) -> None:
    try:
        get_minio_client().remove_object(settings.minio_bucket, object_path)
    except Exception as exc:
        logger.warning(f"MinIO对象清理失败: path={object_path}, error={exc}")


async def _delete_document_safely(db: DBSession, doc: Document) -> None:
    try:
        await db.delete(doc)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning(f"Document记录清理失败: doc_id={doc.id}, error={exc}")


def _document_response(doc: Document, status_override: Optional[str] = None) -> DocumentResponse:
    return DocumentResponse(
        id=str(doc.id),
        knowledge_base_id=str(doc.knowledge_base_id),
        title=doc.title,
        file_path=doc.file_path,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=status_override or doc.status,
        source_type=doc.source_type or "local",
        source_url=doc.source_url,
        indexed_at=doc.indexed_at,
        created_at=doc.created_at,
    )


async def _persist_document(
    db: DBSession,
    kb_id: str,
    *,
    title: str,
    storage_filename: str,
    file_content: bytes,
    file_type: str,
    source_type: str = "local",
    source_url: Optional[str] = None,
) -> Document:
    if file_type not in ALLOWED_TYPES:
        raise ValidationException(f"不支持的文件类型: {file_type}, 支持类型: {', '.join(ALLOWED_TYPES)}")

    file_size = len(file_content)
    if file_size > MAX_FILE_SIZE:
        raise ValidationException(f"文件过大: {file_size/1024/1024:.1f}MB, 最大支持: {MAX_FILE_SIZE/1024/1024:.0f}MB")

    doc_id = uuid.uuid4()
    file_path = f"{kb_id}/{doc_id}/{storage_filename}"

    try:
        await asyncio.to_thread(_upload_bytes_to_minio, file_path, file_content)
    except Exception as exc:
        logger.error(f"MinIO上传失败: {exc}")
        raise ValidationException(f"文件上传失败: {str(exc)}")

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
    db.add(doc)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        _remove_minio_object_safely(file_path)
        logger.error(f"Document记录创建失败: {exc}")
        raise ValidationException(f"文档记录创建失败: {str(exc)}")
    await db.refresh(doc)

    try:
        from core.tasks.indexing import index_document_task
        task = index_document_task.delay(str(doc.id))
        logger.info(f"Celery任务已提交: doc_id={doc.id}, task_id={task.id}, source={source_type}")
    except Exception as exc:
        logger.error(f"Celery任务提交失败: {doc.id}, error={exc}")
        _remove_minio_object_safely(file_path)
        await _delete_document_safely(db, doc)
        raise ValidationException(f"索引任务提交失败: {str(exc)}")

    return doc


@router.get("")
async def list_documents(
    kb_id: str,
    db: DBSession,
    current_user: CurrentUser,
    page: int = 1,
    page_size: int = 20,
):
    kb = await require_visible_kb(db, current_user, uuid.UUID(kb_id))

    query = (
        select(Document)
        .where(Document.knowledge_base_id == kb.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    docs = result.scalars().all()

    items = [
        DocumentListResponse(
            id=str(doc.id),
            title=doc.title,
            file_type=doc.file_type,
            file_size=doc.file_size,
            status=doc.status,
            source_type=doc.source_type or "local",
            chunk_count=doc.chunk_count or 0,
            created_at=doc.created_at,
        )
        for doc in docs
    ]

    return Response(data=items)


# 配置常量
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_TYPES = [
    "pdf",
    "doc",
    "docx",
    "txt",
    "md",
    "xlsx",
    "xls",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "bmp",
]


@router.post("", response_model=Response[DocumentResponse])
async def upload_document(
    kb_id: str,
    file: UploadFile,
    db: DBSession,
    current_user: CurrentUser,
):
    """上传文档API - 支持幂等性、文件校验、Celery任务队列"""
    logger.info(f"[Upload] 进入上传函数, kb_id={kb_id}, filename={file.filename}")
    
    # 1. 权限与知识库范围检查
    kb = await require_manage_kb(db, current_user, uuid.UUID(kb_id))
    logger.info(f"[Upload] 权限检查通过, user={current_user.id}")
    logger.info(f"[Upload] 知识库验证通过, kb_id={kb_id}, kb_name={kb.name}")

    # 3. 文件格式校验
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if file_ext not in ALLOWED_TYPES:
        logger.warning(f"[Upload] 文件格式不支持, ext={file_ext}")
        raise ValidationException(f"不支持的文件类型: {file_ext}, 支持类型: {', '.join(ALLOWED_TYPES)}")
    logger.info(f"[Upload] 文件格式校验通过, ext={file_ext}")

    # 4. 读取文件内容并计算MD5
    file_content = await file.read()
    file_size = len(file_content)
    logger.info(f"[Upload] 文件读取完成, size={file_size/1024/1024:.2f}MB")
    
    # 5. 文件大小限制
    if file_size > MAX_FILE_SIZE:
        logger.warning(f"[Upload] 文件过大, size={file_size/1024/1024:.1f}MB")
        raise ValidationException(f"文件过大: {file_size/1024/1024:.1f}MB, 最大支持: {MAX_FILE_SIZE/1024/1024:.0f}MB")
    logger.info(f"[Upload] 文件大小校验通过")
    
    # 6. 计算MD5用于幂等性
    file_hash = hashlib.md5(file_content).hexdigest()
    logger.info(f"[Upload] MD5计算完成, hash={file_hash[:16]}...")
    
    # 7. 幂等性检查 - 查询相同file_hash且状态为ready的文档
    existing_doc = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == uuid.UUID(kb_id),
            Document.file_hash == file_hash,
        )
    )
    existing = existing_doc.scalar_one_or_none()
    if existing:
        if existing.status == "ready":
            logger.info(f"文档已存在且已索引: {existing.id}, file_hash: {file_hash}")
            return Response(
                data=_document_response(existing, status_override="already_indexed"),
                msg="文档已存在且已索引完成",
            )
        elif existing.status in ("pending", "indexing"):
            logger.info(f"文档已在索引队列中: {existing.id}")
            return Response(
                data=_document_response(existing),
                msg="文档已在索引中",
            )

    doc = await _persist_document(
        db,
        kb_id,
        title=file.filename or "untitled",
        storage_filename=file.filename or "untitled",
        file_content=file_content,
        file_type=file_ext,
        source_type="local",
        source_url=None,
    )

    return Response(
        data=_document_response(doc),
        msg="文档上传成功，已加入索引队列",
    )


@router.post("/from-source", response_model=Response[DocumentResponse])
async def import_from_source(
    kb_id: str,
    body: DocumentFromSourceRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    """从外部源导入文档（飞书、Google Drive等）"""
    from core.sources.registry import get_source
    import tempfile
    import os

    # 1. 权限检查
    kb = await require_manage_kb(db, current_user, uuid.UUID(kb_id))

    # 2. 从外部源获取文档
    source = get_source(body.source_type)
    try:
        result = await source.fetch(body.url, title=body.title)
    except Exception as e:
        raise ValidationException(f"从 {body.source_type} 获取文档失败: {str(e)}")

    # 3. 文件类型校验
    if result.file_type not in ALLOWED_TYPES:
        raise ValidationException(
            f"不支持的文件类型: {result.file_type}, 支持类型: {', '.join(ALLOWED_TYPES)}"
        )

    # 4. 文件大小校验
    if result.content_length > MAX_FILE_SIZE:
        raise ValidationException(
            f"文件过大: {result.content_length / 1024 / 1024:.1f}MB, 最大支持100MB"
        )

    # 5. MD5 幂等检查
    file_hash = hashlib.md5(result.content).hexdigest()
    existing_doc = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == uuid.UUID(kb_id),
            Document.file_hash == file_hash,
        )
    )
    existing = existing_doc.scalar_one_or_none()
    if existing:
        status_msg = "already_indexed" if existing.status == "ready" else existing.status
        return Response(
            data=DocumentResponse(
                id=str(existing.id),
                knowledge_base_id=str(existing.knowledge_base_id),
                title=existing.title,
                file_path=existing.file_path,
                file_type=existing.file_type,
                file_size=existing.file_size,
                status=status_msg,
                source_type=existing.source_type or "local",
                source_url=existing.source_url,
                indexed_at=existing.indexed_at,
                created_at=existing.created_at,
            ),
            msg="文档已存在" if existing.status == "ready" else "文档正在索引中",
        )

    # 6. 上传到 MinIO
    doc_id = uuid.uuid4()
    filename = result.filename or f"{body.source_type}_{doc_id}.{result.file_type}"
    file_path = f"{kb_id}/{doc_id}/{filename}"

    minio_client = get_minio_client()
    if not minio_client.bucket_exists(settings.minio_bucket):
        minio_client.make_bucket(settings.minio_bucket)

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp()
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(result.content)
        minio_client.fput_object(settings.minio_bucket, file_path, tmp_path)
    except Exception as e:
        raise ValidationException(f"存储上传失败: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # 7. 创建 Document 记录
    doc = Document(
        id=doc_id,
        knowledge_base_id=uuid.UUID(kb_id),
        title=filename,
        file_path=file_path,
        file_type=result.file_type,
        file_size=result.content_length,
        file_hash=file_hash,
        source_type=result.source_type,
        source_url=result.source_url,
        status="pending",
        progress=0,
    )
    db.add(doc)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        _remove_minio_object_safely(file_path)
        logger.error(f"Document记录创建失败: {exc}")
        raise ValidationException(f"文档记录创建失败: {str(exc)}")
    await db.refresh(doc)

    # 8. 提交 Celery 索引任务
    try:
        from core.tasks.indexing import index_document_task
        task = index_document_task.delay(str(doc.id))
        logger.info(f"Celery任务已提交: doc_id={doc.id}, task_id={task.id}, source={result.source_type}")
    except Exception as e:
        logger.error(f"Celery任务提交失败: {doc.id}, error={e}")
        _remove_minio_object_safely(file_path)
        await _delete_document_safely(db, doc)
        raise ValidationException(f"索引任务提交失败: {str(e)}")

    return Response(
        data=DocumentResponse(
            id=str(doc.id),
            knowledge_base_id=str(doc.knowledge_base_id),
            title=doc.title,
            file_path=doc.file_path,
            file_type=doc.file_type,
            file_size=doc.file_size,
            status=doc.status,
            source_type=doc.source_type,
            source_url=doc.source_url,
            indexed_at=doc.indexed_at,
            created_at=doc.created_at,
        ),
        msg=f"文档已从 {body.source_type} 导入，正在索引",
    )


@router.get("/{doc_id}", response_model=Response[DocumentResponse])
async def get_document(
    kb_id: str,
    doc_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    await require_visible_kb(db, current_user, uuid.UUID(kb_id))
    result = await db.execute(
        select(Document).where(
            Document.id == uuid.UUID(doc_id),
            Document.knowledge_base_id == uuid.UUID(kb_id),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundException("Document not found")

    return Response(
        data=DocumentResponse(
            id=str(doc.id),
            knowledge_base_id=str(doc.knowledge_base_id),
            title=doc.title,
            file_path=doc.file_path,
            file_type=doc.file_type,
            file_size=doc.file_size,
            status=doc.status,
            source_type=doc.source_type or "local",
            source_url=doc.source_url,
            indexed_at=doc.indexed_at,
            created_at=doc.created_at,
        )
    )


@router.post("/{doc_id}/reindex", response_model=Response[None])
async def reindex_document(
    kb_id: str,
    doc_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    await require_manage_kb(db, current_user, uuid.UUID(kb_id))

    result = await db.execute(
        select(Document).where(
            Document.id == uuid.UUID(doc_id),
            Document.knowledge_base_id == uuid.UUID(kb_id),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundException("Document not found")

    doc.status = "pending"
    doc.progress = 0
    doc.error_message = None
    await db.commit()

    # 调用Celery任务
    try:
        from core.tasks.indexing import index_document_task
        task = index_document_task.delay(str(doc.id))
        logger.info(f"Reindex Celery task: {task.id}")
    except Exception as e:
        logger.error(f"Celery任务提交失败: {doc.id}, error={e}")
        raise ValidationException(f"索引任务启动失败: {str(e)}")

    return Response(data=None, msg="索引任务已启动")


@router.get("/{doc_id}/indexing-status", response_model=Response[dict])
async def get_indexing_status(
    kb_id: str,
    doc_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    await require_visible_kb(db, current_user, uuid.UUID(kb_id))
    result = await db.execute(
        select(Document).where(
            Document.id == uuid.UUID(doc_id),
            Document.knowledge_base_id == uuid.UUID(kb_id),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundException("Document not found")

    from sqlalchemy import func
    chunk_count = await db.scalar(
        select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
    ) or 0

    # 使用Document.progress
    if doc.progress:
        progress = doc.progress
    elif doc.status == "ready":
        progress = 100
    elif doc.status == "indexing":
        progress = min(chunk_count * 10, 90)
    else:
        progress = 0

    return Response(data={
        "id": str(doc.id),
        "title": doc.title,
        "status": doc.status,
        "error_message": getattr(doc, 'error_message', None),
        "indexed_at": doc.indexed_at.isoformat() if doc.indexed_at else None,
        "chunk_count": chunk_count,
        "progress": progress,
    })


@router.delete("/{doc_id}", response_model=Response[None])
async def delete_document(
    kb_id: str,
    doc_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    await require_manage_kb(db, current_user, uuid.UUID(kb_id))
    
    result = await db.execute(
        select(Document).where(
            Document.id == uuid.UUID(doc_id),
            Document.knowledge_base_id == uuid.UUID(kb_id),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundException("Document not found")

    try:
        minio_client = get_minio_client()
        minio_client.remove_object(settings.minio_bucket, doc.file_path)
    except Exception:
        pass

    await db.delete(doc)
    await db.commit()

    return Response(data=None)

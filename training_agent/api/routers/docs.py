import logging
import uuid

from fastapi import APIRouter, Query, UploadFile

from api.deps import CurrentUser, DBSession
from api.schemas.common import Response
from api.schemas.doc import (
    DocumentFromSourceRequest,
    DocumentListResponse,
    DocumentPageResponse,
    DocumentResponse,
)
from core.application.documents import ImportDocumentUseCase
from core.domain.knowledge_base.aggregates import Document as DomainDocument
from core.exceptions import NotFoundException
from core.infrastructure.db.repositories import (
    ChunkRepositoryImpl,
    DocumentRepositoryImpl,
)
from core.permissions import require_visible_kb
from models.tables import Document

logger = logging.getLogger(__name__)

router = APIRouter()


def _document_response(doc: Document, status_override: str | None = None) -> DocumentResponse:
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


@router.get("")
async def list_documents(
    kb_id: str,
    db: DBSession,
    current_user: CurrentUser,
    page: int = 1,
    page_size: int = 20,
    with_total: bool = Query(False, description="返回分页元数据 (total / page / page_size / counts)"),
    q: str | None = Query(None, description="按 title 模糊搜索"),
    status: str | None = Query(None, description="文档状态过滤: ready / indexing / pending / error"),
    sort: str = Query("created_desc", description="排序: created_desc / created_asc / name_asc / name_desc"),
):
    """
    文档列表接口。

    兼容原则:
    - with_total=False: 返回 { code, data: [...items] }, 旧调用方不受影响。
    - with_total=True: 返回 DocumentPageResponse (items + total + page + page_size + counts)。
    """
    kb = await require_visible_kb(db, current_user, uuid.UUID(kb_id))

    # 过滤 + 排序 + 分页 + 计数 全部下沉至 DocumentRepository
    items, total, counts = await DocumentRepositoryImpl(db).list_by_kb_paginated(
        kb_id=kb.id,
        page=page,
        page_size=page_size,
        q=q,
        status=status,
        sort=sort,
    )

    items_dto = [
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
        for doc in items
    ]

    # 兼容模式: 直接返回 items
    if not with_total:
        return Response(data=items_dto)

    # 完整分页模式: 返回 total + counts
    return Response(data=DocumentPageResponse(
        items=items_dto,
        total=total,
        page=page,
        page_size=page_size,
        counts=counts,
    ))


@router.post("", response_model=Response[DocumentResponse])
async def upload_document(
    kb_id: str,
    file: UploadFile,
    db: DBSession,
    current_user: CurrentUser,
):
    """上传文档API - 支持幂等性、文件校验、Celery任务队列"""
    logger.info(f"[Upload] 进入上传函数, kb_id={kb_id}, filename={file.filename}")

    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""
    file_content = await file.read()

    use_case = ImportDocumentUseCase(db)
    result = await use_case.upload_document(
        kb_id=kb_id,
        filename=file.filename or "untitled",
        content=file_content,
        file_type=file_ext,
        current_user=current_user,
    )

    return Response(
        data=_document_response(result.document, result.status_override),
        msg=result.message,
    )


@router.post("/from-source", response_model=Response[DocumentResponse])
async def import_from_source(
    kb_id: str,
    body: DocumentFromSourceRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    """从外部源导入文档（飞书、Google Drive等）"""
    use_case = ImportDocumentUseCase(db)
    result = await use_case.import_from_source(
        kb_id=kb_id,
        source_type=body.source_type,
        url=body.url,
        title=body.title,
        current_user=current_user,
    )

    return Response(
        data=_document_response(result.document, result.status_override),
        msg=result.message,
    )


@router.get("/{doc_id}", response_model=Response[DocumentResponse])
async def get_document(
    kb_id: str,
    doc_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    kb = await require_visible_kb(db, current_user, uuid.UUID(kb_id))
    doc = await DocumentRepositoryImpl(db).get_by_id(uuid.UUID(doc_id))
    if not doc or doc.knowledge_base_id != kb.id:
        raise NotFoundException("Document not found")

    return Response(data=_document_response(doc))


@router.post("/{doc_id}/reindex", response_model=Response[None])
async def reindex_document(
    kb_id: str,
    doc_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    use_case = ImportDocumentUseCase(db)
    await use_case.reindex_document(
        kb_id=kb_id, doc_id=doc_id, current_user=current_user
    )
    return Response(data=None, msg="索引任务已启动")


@router.get("/{doc_id}/indexing-status", response_model=Response[dict])
async def get_indexing_status(
    kb_id: str,
    doc_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    kb = await require_visible_kb(db, current_user, uuid.UUID(kb_id))
    doc = await DocumentRepositoryImpl(db).get_by_id(uuid.UUID(doc_id))
    if not doc or doc.knowledge_base_id != kb.id:
        raise NotFoundException("Document not found")

    chunk_count = await ChunkRepositoryImpl(db).count_by_document(doc.id)

    # 进度优先用存储值，否则由领域实体推导（ready→100, indexing→min(chunk*10,90), else→0）
    progress = doc.progress or DomainDocument.from_orm(doc).derive_progress()

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
    use_case = ImportDocumentUseCase(db)
    await use_case.delete_document(
        kb_id=kb_id, doc_id=doc_id, current_user=current_user
    )
    return Response(data=None)

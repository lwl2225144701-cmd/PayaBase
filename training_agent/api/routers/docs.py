import logging
import uuid

from fastapi import APIRouter, Query, UploadFile
from sqlalchemy import func, select

from api.deps import CurrentUser, DBSession
from api.schemas.common import Response
from api.schemas.doc import (
    DocumentFromSourceRequest,
    DocumentListResponse,
    DocumentPageResponse,
    DocumentResponse,
)
from core.application.documents import ImportDocumentUseCase
from core.exceptions import NotFoundException
from core.permissions import require_visible_kb
from models.tables import Chunk, Document

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

    # 边界保护
    page = max(1, page)
    allowed_sizes = {10, 25, 50}
    if page_size not in allowed_sizes:
        # 限制在 10/25/50, 默认 10, 最大不超过 100
        if page_size > 100:
            page_size = 100
        elif page_size < 10:
            page_size = 10
        else:
            page_size = 10  # 其它非白名单值兜底为 10

    # 基础过滤条件
    base_filters = [Document.knowledge_base_id == kb.id]
    if q:
        # 按 title 模糊搜索, 走 ILIKE (PostgreSQL 不区分大小写)
        base_filters.append(Document.title.ilike(f"%{q}%"))
    if status and status != "all":
        if status == "ready":
            base_filters.append(Document.status == "ready")
        elif status == "error":
            base_filters.append(Document.status == "error")
        elif status == "indexing":
            # "indexing" tab 同时包含 indexing + pending
            base_filters.append(Document.status.in_(["indexing", "pending"]))
        elif status == "pending":
            base_filters.append(Document.status == "pending")
        # 其它值忽略, 不加 status 条件

    # 排序
    if sort == "created_asc":
        order_by = Document.created_at.asc()
    elif sort == "name_asc":
        order_by = Document.title.asc()
    elif sort == "name_desc":
        order_by = Document.title.desc()
    else:
        # 默认 created_desc
        order_by = Document.created_at.desc()

    # 查询 items (带 offset/limit)
    items_query = (
        select(Document)
        .where(*base_filters)
        .order_by(order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items_result = await db.execute(items_query)
    docs = items_result.scalars().all()

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

    # 兼容模式: 直接返回 items
    if not with_total:
        return Response(data=items)

    # 完整分页模式: 返回 total + counts
    # total = 在 base_filters 之下的全部命中条数
    total_query = select(func.count(Document.id)).where(*base_filters)
    total = await db.scalar(total_query) or 0

    # counts: 按 kb 全库统计各状态数量
    # NOTE: 当前实现不把 q 纳入 counts, 保持 counts 反映"该 KB 整体状态分布",
    #       避免每次搜索都重算 4 个 count。
    counts_query = select(Document.status, func.count(Document.id)).where(
        Document.knowledge_base_id == kb.id
    ).group_by(Document.status)
    counts_result = await db.execute(counts_query)
    status_rows = counts_result.all()

    counts = {
        "all": sum(c for _, c in status_rows),
        "ready": 0,
        "indexing": 0,  # indexing + pending 之和
        "error": 0,
    }
    for s, c in status_rows:
        if s == "ready":
            counts["ready"] += c
        elif s in ("indexing", "pending"):
            counts["indexing"] += c
        elif s == "error":
            counts["error"] += c

    return Response(data=DocumentPageResponse(
        items=items,
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
    use_case = ImportDocumentUseCase(db)
    await use_case.delete_document(
        kb_id=kb_id, doc_id=doc_id, current_user=current_user
    )
    return Response(data=None)

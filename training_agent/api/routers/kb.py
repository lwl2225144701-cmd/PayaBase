import uuid
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response
from api.schemas.kb import KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse, KnowledgeBaseListResponse
from core.permissions import (
    can_manage_kb,
    can_manage_knowledge_bases,
    is_super_admin,
    knowledge_base_visibility_filter,
    require_manage_kb,
)
from core.exceptions import NotFoundException
from models.tables import KnowledgeBase, Document, Department

router = APIRouter()


def _kb_response(kb: KnowledgeBase, doc_count: int, current_user: CurrentUser) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        id=str(kb.id),
        tenant_id=str(kb.tenant_id),
        department_id=str(kb.department_id) if kb.department_id else None,
        department_name=kb.department.name if kb.department else None,
        name=kb.name,
        description=kb.description,
        embedding_model=kb.embedding_model,
        doc_count=doc_count,
        can_manage=can_manage_kb(current_user, kb),
        created_at=kb.created_at,
    )


@router.get("", response_model=Response[list[KnowledgeBaseListResponse]])
async def list_knowledge_bases(
    db: DBSession,
    current_user: CurrentUser,
    page: int = 1,
    page_size: int = 20,
):
    query = (
        select(KnowledgeBase)
        .where(knowledge_base_visibility_filter(current_user))
        .options(joinedload(KnowledgeBase.department))
        .order_by(KnowledgeBase.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    kb_list = result.scalars().unique().all()

    kb_ids = [kb.id for kb in kb_list]
    doc_count_map: dict[uuid.UUID, int] = {}
    if kb_ids:
        count_result = await db.execute(
            select(
                Document.knowledge_base_id,
                func.count(Document.id),
            )
            .where(Document.knowledge_base_id.in_(kb_ids))
            .group_by(Document.knowledge_base_id)
        )
        doc_count_map = {kb_id: count for kb_id, count in count_result.all()}

    items = [
        KnowledgeBaseListResponse(
            id=str(kb.id),
            name=kb.name,
            description=kb.description,
            department_id=str(kb.department_id) if kb.department_id else None,
            department_name=kb.department.name if kb.department else None,
            doc_count=doc_count_map.get(kb.id, 0),
            can_manage=can_manage_kb(current_user, kb),
            created_at=kb.created_at,
        )
        for kb in kb_list
    ]

    return Response(data=items)


@router.post("", response_model=Response[KnowledgeBaseResponse])
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    if not can_manage_knowledge_bases(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅知识库管理员可创建知识库",
        )

    if is_super_admin(current_user):
        department_id = uuid.UUID(data.department_id) if data.department_id else None
        if department_id:
            dept = await db.scalar(
                select(Department).where(
                    Department.id == department_id,
                    Department.tenant_id == uuid.UUID(current_user.tenant_id),
                )
            )
            if not dept:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="部门不存在",
                )
    else:
        if not current_user.department_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前培训管理员未绑定部门",
            )
        if data.department_id and data.department_id != current_user.department_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="培训管理员只能创建本部门知识库",
            )
        department_id = uuid.UUID(current_user.department_id)

    kb = KnowledgeBase(
        tenant_id=uuid.UUID(current_user.tenant_id),
        department_id=department_id,
        name=data.name,
        description=data.description,
        embedding_model=data.embedding_model,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb, attribute_names=["department"])

    return Response(
        data=_kb_response(kb, 0, current_user)
    )


@router.get("/{kb_id}", response_model=Response[KnowledgeBaseResponse])
async def get_knowledge_base(
    kb_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(KnowledgeBase)
        .options(joinedload(KnowledgeBase.department))
        .where(knowledge_base_visibility_filter(current_user), KnowledgeBase.id == uuid.UUID(kb_id))
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundException("Knowledge base not found")

    doc_count = await db.scalar(
        select(func.count()).select_from(Document).where(
            Document.knowledge_base_id == kb.id
        )
    ) or 0

    return Response(
        data=_kb_response(kb, doc_count, current_user)
    )


@router.put("/{kb_id}", response_model=Response[KnowledgeBaseResponse])
async def update_knowledge_base(
    kb_id: str,
    data: KnowledgeBaseUpdate,
    db: DBSession,
    current_user: CurrentUser,
):
    kb = await require_manage_kb(db, current_user, uuid.UUID(kb_id))

    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description

    await db.commit()
    await db.refresh(kb, attribute_names=["department"])

    doc_count = await db.scalar(
        select(func.count()).select_from(Document).where(
            Document.knowledge_base_id == kb.id
        )
    ) or 0

    return Response(
        data=_kb_response(kb, doc_count, current_user)
    )


@router.delete("/{kb_id}", response_model=Response[None])
async def delete_knowledge_base(
    kb_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    kb = await require_manage_kb(db, current_user, uuid.UUID(kb_id))

    await db.delete(kb)
    await db.commit()

    return Response(data=None)

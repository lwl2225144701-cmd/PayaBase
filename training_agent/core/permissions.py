import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import ColumnElement

from api.schemas.common import UserInfo
from models.tables import KnowledgeBase


SUPER_ADMIN_ROLE = "admin"
TRAINING_ADMIN_ROLE = "training_admin"
USER_ROLE = "user"


def _uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    return uuid.UUID(value) if value else None


def is_super_admin(user: UserInfo) -> bool:
    return user.role == SUPER_ADMIN_ROLE


def is_training_admin(user: UserInfo) -> bool:
    return user.role == TRAINING_ADMIN_ROLE


def can_manage_knowledge_bases(user: UserInfo) -> bool:
    return is_super_admin(user) or is_training_admin(user)


def can_manage_kb(user: UserInfo, kb: KnowledgeBase) -> bool:
    if is_super_admin(user):
        return str(kb.tenant_id) == user.tenant_id
    if not is_training_admin(user) or not user.department_id:
        return False
    return str(kb.tenant_id) == user.tenant_id and str(kb.department_id) == user.department_id


def knowledge_base_visibility_filter(user: UserInfo) -> ColumnElement[bool]:
    tenant_id = _uuid(user.tenant_id)
    if is_super_admin(user):
        return KnowledgeBase.tenant_id == tenant_id

    department_id = _uuid(user.department_id)
    if department_id is None:
        return (KnowledgeBase.tenant_id == tenant_id) & (KnowledgeBase.department_id.is_(None))

    return (KnowledgeBase.tenant_id == tenant_id) & (
        or_(KnowledgeBase.department_id == department_id, KnowledgeBase.department_id.is_(None))
    )


def visible_knowledge_base_query(user: UserInfo):
    return select(KnowledgeBase).where(knowledge_base_visibility_filter(user))


async def require_visible_kb(db, user: UserInfo, kb_id: uuid.UUID) -> KnowledgeBase:
    result = await db.execute(
        visible_knowledge_base_query(user)
        .options(joinedload(KnowledgeBase.department))
        .where(KnowledgeBase.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )
    return kb


async def require_manage_kb(db, user: UserInfo, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = await require_visible_kb(db, user, kb_id)
    if not can_manage_kb(user, kb):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限管理该知识库",
        )
    return kb

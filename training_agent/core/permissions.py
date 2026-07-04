import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import ColumnElement

from api.schemas.common import UserInfo
from models.tables import KnowledgeBase


SUPER_ADMIN_ROLE = "admin"
ADMIN_ROLE = "training_admin"  # DB 中仍存储为 training_admin,代码层语义已变为 admin
USER_ROLE = "user"


def _uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    return uuid.UUID(value) if value else None


def is_super_admin(user: UserInfo) -> bool:
    return user.role == SUPER_ADMIN_ROLE


def is_admin(user: UserInfo) -> bool:
    """检查用户是否为管理员(兼容 DB 中的 training_admin 值)"""
    return user.role == ADMIN_ROLE


# 向后兼容:旧代码仍可通过 is_training_admin() 调用
is_training_admin = is_admin


def can_manage_knowledge_bases(user: UserInfo) -> bool:
    return is_super_admin(user) or is_admin(user)


def can_manage_kb(user: UserInfo, kb: KnowledgeBase) -> bool:
    """admin / training_admin 都可以管理当前 tenant 下知识库，不再依赖 department_id"""
    if not is_super_admin(user) and not is_admin(user):
        return False
    return str(kb.tenant_id) == user.tenant_id


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

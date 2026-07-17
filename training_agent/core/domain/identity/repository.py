"""Tenant / User 仓储端口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from models.tables import Tenant, User


class TenantRepository(Protocol):
    """租户聚合根仓储。"""

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        ...

    async def get_user(self, user_id: UUID) -> User | None:
        """获取用户（含部门关系）。"""
        ...

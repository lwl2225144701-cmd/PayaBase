"""Identity 领域实体（Phase 4 充实）。

聚合根：User（含 Tenant / Department 归属）。此前角色判断散落在权限模块，
本模块收拢为基础不变量。
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass
class User:
    id: UUID
    tenant_id: UUID
    name: str
    email: str
    role: str = "user"
    department_id: UUID | None = None
    hr_user_id: str | None = None
    sso_id: str | None = None

    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def from_orm(cls, orm) -> User:
        return cls(
            id=orm.id,
            tenant_id=orm.tenant_id,
            name=orm.name,
            email=orm.email,
            role=orm.role or "user",
            department_id=orm.department_id,
            hr_user_id=orm.hr_user_id,
            sso_id=orm.sso_id,
        )

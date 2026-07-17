"""用户身份值对象（Identity 上下文）。

认证后构造，跨层传递。原定义在 api/schemas/common.py，
Phase 1 移至领域层以消除 core→api 反向依赖；api/schemas/common.py 保留 re-export。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class UserInfo(BaseModel):
    """认证后的用户身份。"""

    id: str
    tenant_id: str
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    hr_user_id: Optional[str] = None
    name: str
    email: str
    role: str = "user"
    is_super_admin: bool = False
    is_admin: bool = False
    is_training_admin: bool = False  # 向后兼容
    can_manage_knowledge_bases: bool = False

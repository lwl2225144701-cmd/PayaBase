"""权限验证中间件"""

import uuid

from fastapi import HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from core.config import settings
from models.tables import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials,
    db: AsyncSession,
) -> User:
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        if payload.get("sub") is None or payload.get("user_id") is None:
            raise credentials_exception
        user_id = uuid.UUID(payload["user_id"])
    except JWTError:
        raise credentials_exception

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    return user


from core.permissions import SUPER_ADMIN_ROLE, ADMIN_ROLE


def require_admin(user: User) -> None:
    """检查是否为管理员"""
    if user.role not in (SUPER_ADMIN_ROLE, ADMIN_ROLE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可访问",
        )

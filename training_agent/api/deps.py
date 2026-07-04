import uuid
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from core.config import settings
from core.permissions import can_manage_knowledge_bases, is_super_admin, is_training_admin
from models.db import get_db
from models.tables import User
from api.schemas.common import TokenPayload, UserInfo

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserInfo:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise credentials_exception

    try:
        token = credentials.credentials
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        token_data = TokenPayload(**payload)
        if token_data.sub is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(
        select(User).options(joinedload(User.department)).where(User.id == uuid.UUID(token_data.user_id))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    return UserInfo(
        id=str(user.id),
        tenant_id=str(user.tenant_id),
        department_id=str(user.department_id) if user.department_id else None,
        department_name=user.department.name if user.department else None,
        hr_user_id=user.hr_user_id,
        name=user.name,
        email=user.email,
        role=user.role,
        is_super_admin=is_super_admin(user),
        is_training_admin=is_training_admin(user),
        can_manage_knowledge_bases=can_manage_knowledge_bases(user),
    )


async def get_optional_current_user(
    authorization: Annotated[Optional[str], Depends(Header)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Optional[UserInfo]:
    if not authorization:
        return None

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return None
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        return await get_current_user(credentials, db)
    except Exception:
        return None


DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserInfo, Depends(get_current_user)]
OptionalCurrentUser = Annotated[Optional[UserInfo], Depends(get_optional_current_user)]

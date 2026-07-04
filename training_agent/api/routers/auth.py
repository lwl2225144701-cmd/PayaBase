from datetime import datetime, timedelta

from fastapi import APIRouter
from jose import jwt
from sqlalchemy import select

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response, TokenData, UserInfo
from core.config import settings
from core.exceptions import ValidationException
from models.tables import User, Tenant, Department

router = APIRouter()


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")


@router.post("/auth/sso", response_model=Response[TokenData])
async def sso_login(
    code: str,
    db: DBSession,
):
    # TODO: Implement actual SSO authentication with HR API
    # This is a placeholder implementation
    code = code.strip()
    if not code:
        raise ValidationException("code 不能为空")

    result = await db.execute(select(User).where(User.sso_id == code))
    user = result.scalar_one_or_none()

    if not user:
        # Create or sync user from HR API (placeholder)
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(name="Default Tenant", config={})
            db.add(tenant)
            await db.commit()
            await db.refresh(tenant)

        role = (
            "admin"
            if code == "admin"
            else "training_admin"
            if code == "training_admin"
            else "user"
        )
        department_id = None
        if role == "training_admin":
            dept = await db.scalar(
                select(Department).where(Department.tenant_id == tenant.id).limit(1)
            )
            department_id = dept.id if dept else None

        user = User(
            tenant_id=tenant.id,
            department_id=department_id,
            name=f"User_{code}",
            email=f"{code}@training.local",
            sso_id=code,
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    token = create_access_token(
        {"sub": user.email, "tenant_id": str(user.tenant_id), "user_id": str(user.id)}
    )

    return Response(
        data=TokenData(
            access_token=token,
            token_type="bearer",
            expires_in=settings.jwt_expire_minutes,
        )
    )


@router.get("/auth/me", response_model=Response[UserInfo])
async def get_current_user_info(current_user: CurrentUser):
    return Response(data=current_user)

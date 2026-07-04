import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.tables import PlatformUser, Tenant, User


class PlatformUserService:
    async def get_or_create_user(
        self,
        db: AsyncSession,
        platform: str,
        platform_user_id: str,
        display_name: str,
        tenant_id: Optional[str] = None,
    ) -> User:
        result = await db.execute(
            select(PlatformUser, User)
            .join(User, User.id == PlatformUser.user_id)
            .where(
                PlatformUser.platform == platform,
                PlatformUser.platform_user_id == platform_user_id,
            )
        )
        row = result.first()
        if row:
            return row[1]

        target_tenant_id = tenant_id
        if not target_tenant_id:
            tenant_res = await db.execute(select(Tenant).order_by(Tenant.created_at.asc()).limit(1))
            tenant = tenant_res.scalar_one_or_none()
            if not tenant:
                raise ValueError("No tenant found for platform user bootstrap")
            target_tenant_id = str(tenant.id)

        safe_platform = platform.lower().strip()
        safe_pid = platform_user_id.strip() or uuid.uuid4().hex[:12]
        email = f"{safe_platform}_{safe_pid}@platform.local"

        user = User(
            tenant_id=uuid.UUID(target_tenant_id),
            name=display_name or f"{platform}:{platform_user_id}",
            email=email,
            role="user",
        )
        db.add(user)
        await db.flush()

        mapping = PlatformUser(
            tenant_id=user.tenant_id,
            user_id=user.id,
            platform=platform,
            platform_user_id=platform_user_id,
            display_name=display_name or None,
        )
        db.add(mapping)
        await db.commit()
        await db.refresh(user)
        return user

    async def bind_user(
        self,
        db: AsyncSession,
        platform: str,
        platform_user_id: str,
        internal_user_id: str,
    ) -> None:
        user_res = await db.execute(select(User).where(User.id == uuid.UUID(internal_user_id)))
        user = user_res.scalar_one_or_none()
        if not user:
            raise ValueError("Internal user not found")

        mapping_res = await db.execute(
            select(PlatformUser).where(
                PlatformUser.platform == platform,
                PlatformUser.platform_user_id == platform_user_id,
            )
        )
        mapping = mapping_res.scalar_one_or_none()
        if mapping:
            mapping.user_id = user.id
            mapping.tenant_id = user.tenant_id
        else:
            mapping = PlatformUser(
                tenant_id=user.tenant_id,
                user_id=user.id,
                platform=platform,
                platform_user_id=platform_user_id,
                display_name=user.name,
            )
            db.add(mapping)
        await db.commit()

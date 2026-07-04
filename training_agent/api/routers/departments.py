import uuid

from fastapi import APIRouter
from sqlalchemy import select

from api.deps import CurrentUser, DBSession
from api.schemas.common import DepartmentResponse, Response
from core.permissions import is_super_admin
from models.tables import Department

router = APIRouter()


@router.get("/departments", response_model=Response[list[DepartmentResponse]])
async def list_departments(
    db: DBSession,
    current_user: CurrentUser,
):
    query = select(Department).where(Department.tenant_id == uuid.UUID(current_user.tenant_id))
    if not is_super_admin(current_user):
        if not current_user.department_id:
            return Response(data=[])
        query = query.where(Department.id == uuid.UUID(current_user.department_id))

    result = await db.execute(query.order_by(Department.name))
    departments = result.scalars().all()

    return Response(
        data=[
            DepartmentResponse(
                id=str(dept.id),
                name=dept.name,
                code=dept.code,
            )
            for dept in departments
        ]
    )

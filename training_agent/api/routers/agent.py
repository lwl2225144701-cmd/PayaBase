import uuid

from fastapi import APIRouter
from sqlalchemy import select

from api.deps import DBSession, CurrentUser
from api.schemas.agent import AgentRunResponse, AgentStepResponse
from api.schemas.common import Response
from core.exceptions import NotFoundException
from models.tables import AgentRun, AgentStep

router = APIRouter()


@router.get("/agent/runs/{run_id}", response_model=Response[AgentRunResponse])
async def get_agent_run(
    run_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(AgentRun).where(
            AgentRun.id == uuid.UUID(run_id),
            AgentRun.tenant_id == uuid.UUID(current_user.tenant_id),
            AgentRun.user_id == uuid.UUID(current_user.id),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundException("Agent run not found")

    return Response(
        data=AgentRunResponse(
            id=str(run.id),
            tenant_id=str(run.tenant_id),
            user_id=str(run.user_id),
            conversation_id=str(run.conversation_id),
            goal=run.goal,
            status=run.status,
            route=run.route,
            current_step=run.current_step,
            next_step=run.next_step,
            completed_steps_summary=run.completed_steps_summary or "",
            plan_snapshot=run.plan_snapshot or {},
            step_history=run.step_history or [],
            artifacts=run.artifacts or [],
            last_error=run.last_error,
            retry_count=run.retry_count,
            budget_remaining=run.budget_remaining,
            created_at=run.created_at,
            updated_at=run.updated_at,
            completed_at=run.completed_at,
        )
    )


@router.get("/agent/runs/{run_id}/steps", response_model=Response[list[AgentStepResponse]])
async def list_agent_steps(
    run_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    run_q = await db.execute(
        select(AgentRun).where(
            AgentRun.id == uuid.UUID(run_id),
            AgentRun.tenant_id == uuid.UUID(current_user.tenant_id),
            AgentRun.user_id == uuid.UUID(current_user.id),
        )
    )
    run = run_q.scalar_one_or_none()
    if not run:
        raise NotFoundException("Agent run not found")

    result = await db.execute(
        select(AgentStep)
        .where(AgentStep.run_id == run.id)
        .order_by(AgentStep.created_at.asc())
    )
    rows = result.scalars().all()

    items = [
        AgentStepResponse(
            id=str(step.id),
            run_id=str(step.run_id),
            step_key=step.step_key,
            step_type=step.step_type,
            step_goal=step.step_goal,
            status=step.status,
            output=step.output or "",
            error=step.error or "",
            tool_trace=step.tool_trace or [],
            created_at=step.created_at,
            updated_at=step.updated_at,
        )
        for step in rows
    ]
    return Response(data=items)


@router.get("/agent/conversations/{conversation_id}/runs/latest", response_model=Response[AgentRunResponse])
async def get_latest_agent_run_by_conversation(
    conversation_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(AgentRun)
        .where(
            AgentRun.conversation_id == uuid.UUID(conversation_id),
            AgentRun.tenant_id == uuid.UUID(current_user.tenant_id),
            AgentRun.user_id == uuid.UUID(current_user.id),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundException("Agent run not found")

    return Response(
        data=AgentRunResponse(
            id=str(run.id),
            tenant_id=str(run.tenant_id),
            user_id=str(run.user_id),
            conversation_id=str(run.conversation_id),
            goal=run.goal,
            status=run.status,
            route=run.route,
            current_step=run.current_step,
            next_step=run.next_step,
            completed_steps_summary=run.completed_steps_summary or "",
            plan_snapshot=run.plan_snapshot or {},
            step_history=run.step_history or [],
            artifacts=run.artifacts or [],
            last_error=run.last_error,
            retry_count=run.retry_count,
            budget_remaining=run.budget_remaining,
            created_at=run.created_at,
            updated_at=run.updated_at,
            completed_at=run.completed_at,
        )
    )

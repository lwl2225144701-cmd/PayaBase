"""Stats Router.

All queries are based on the messages table (not query_logs,
which is never written to by the chat flow). Tenant isolation
is enforced via join on conversations.tenant_id.
"""

from datetime import datetime
import uuid

from fastapi import APIRouter
import httpx
from sqlalchemy import select, func, distinct, cast, Date, case, text

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response
from api.schemas.stats import UsageStats, QueryStat, TrendPoint, AgentMetrics, AgentTrendPoint, SearchMetrics, SearchTrendPoint
from core.config import settings
from core.permissions import is_super_admin, is_admin, knowledge_base_visibility_filter
from models.tables import Conversation, Message, KnowledgeBase, AgentRun, AgentStep

router = APIRouter()


def _tenant_filter():
    """Return a where clause joining messages→conversations by tenant."""
    return Conversation.tenant_id == func.current_setting("app.tenant_id")  # placeholder


def _conversation_scope_filter(current_user: CurrentUser):
    tenant_id = uuid.UUID(current_user.tenant_id)
    if is_super_admin(current_user):
        return Conversation.tenant_id == tenant_id
    if is_admin(current_user):
        visible_kb_ids = select(KnowledgeBase.id).where(
            knowledge_base_visibility_filter(current_user)
        )
        return (Conversation.tenant_id == tenant_id) & (
            Conversation.knowledge_base_id.in_(visible_kb_ids)
        )
    return (Conversation.tenant_id == tenant_id) & (
        Conversation.user_id == uuid.UUID(current_user.id)
    )


def _empty_search_metrics() -> SearchMetrics:
    return SearchMetrics()


@router.get("/usage", response_model=Response[UsageStats])
async def get_usage_stats(
    db: DBSession,
    current_user: CurrentUser,
):
    # Base join: messages → conversations, filtered by tenant
    base = (
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(_conversation_scope_filter(current_user))
    )

    # Total queries = user messages
    total_queries = await db.scalar(
        select(func.count()).select_from(
            base.where(Message.role == "user").subquery()
        )
    ) or 0

    # Total messages = all messages
    total_messages = await db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    # Average response time = avg latency_ms of assistant messages with latency > 0
    avg_latency = await db.scalar(
        select(func.avg(Message.latency_ms)).select_from(
            base.where(
                Message.role == "assistant",
                Message.latency_ms > 0,
            ).subquery()
        )
    ) or 0

    # Today queries
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_queries = await db.scalar(
        select(func.count()).select_from(
            base.where(
                Message.role == "user",
                Message.created_at >= today_start,
            ).subquery()
        )
    ) or 0

    # Active users today (distinct user_id from conversations with messages today)
    active_users = await db.scalar(
        select(func.count(distinct(Conversation.user_id)))
        .select_from(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            _conversation_scope_filter(current_user),
            Message.created_at >= today_start,
        )
    ) or 0

    # Average token consumption (messages with token_count > 0)
    avg_tokens = await db.scalar(
        select(func.avg(Message.token_count)).select_from(
            base.where(Message.token_count > 0).subquery()
        )
    ) or 0

    data = UsageStats(
        total_queries=total_queries,
        total_messages=total_messages,
        avg_latency_ms=int(avg_latency),
        today_queries=today_queries,
        active_users=active_users,
        avg_tokens=int(avg_tokens),
    )

    return Response(data=data)


@router.get("/queries", response_model=Response[list[QueryStat]])
async def get_popular_queries(
    db: DBSession,
    current_user: CurrentUser,
    limit: int = 10,
):
    query = (
        select(
            Message.content,
            func.count(Message.id).label("count"),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            _conversation_scope_filter(current_user),
            Message.role == "user",
            Message.content.isnot(None),
            Message.content != "",
        )
        .group_by(Message.content)
        .order_by(func.count(Message.id).desc())
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    data = [QueryStat(query=row.content, count=row.count) for row in rows]

    return Response(data=data)


@router.get("/trend", response_model=Response[list[TrendPoint]])
async def get_query_trend(
    db: DBSession,
    current_user: CurrentUser,
    days: int = 7,
):
    # Calculate start date
    from datetime import timedelta
    start_date = datetime.utcnow() - timedelta(days=days)

    query = (
        select(
            cast(Message.created_at, Date).label("date"),
            func.count(Message.id).label("count"),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            _conversation_scope_filter(current_user),
            Message.role == "user",
            Message.created_at >= start_date,
        )
        .group_by(cast(Message.created_at, Date))
        .order_by(cast(Message.created_at, Date))
    )

    result = await db.execute(query)
    rows = result.all()

    data = [TrendPoint(date=str(row.date), count=row.count) for row in rows]

    return Response(data=data)


@router.get("/agent", response_model=Response[AgentMetrics])
async def get_agent_metrics(
    db: DBSession,
    current_user: CurrentUser,
    days: int = 7,
):
    scope = _conversation_scope_filter(current_user)
    from datetime import timedelta
    start_date = datetime.utcnow() - timedelta(days=days)
    run_scope = (scope, AgentRun.created_at >= start_date)

    total_runs = await db.scalar(
        select(func.count(AgentRun.id))
        .select_from(AgentRun)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(*run_scope)
    ) or 0
    completed_runs = await db.scalar(
        select(func.count(AgentRun.id))
        .select_from(AgentRun)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(*run_scope, AgentRun.status == "completed")
    ) or 0
    failed_runs = await db.scalar(
        select(func.count(AgentRun.id))
        .select_from(AgentRun)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(*run_scope, AgentRun.status == "failed")
    ) or 0

    retry_triggered_runs = await db.scalar(
        select(func.count(distinct(AgentStep.run_id)))
        .select_from(AgentStep)
        .join(AgentRun, AgentStep.run_id == AgentRun.id)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(*run_scope, AgentStep.step_type == "retry_decision")
    ) or 0
    retry_success_runs = await db.scalar(
        select(func.count(distinct(AgentStep.run_id)))
        .select_from(AgentStep)
        .join(AgentRun, AgentStep.run_id == AgentRun.id)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(*run_scope, AgentStep.step_type == "retry_decision", AgentStep.status == "success")
    ) or 0

    steps_per_run_subq = (
        select(
            AgentStep.run_id.label("run_id"),
            func.count(AgentStep.id).label("step_count"),
        )
        .join(AgentRun, AgentStep.run_id == AgentRun.id)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(*run_scope)
        .group_by(AgentStep.run_id)
        .subquery()
    )
    avg_steps_per_run = await db.scalar(
        select(func.avg(steps_per_run_subq.c.step_count))
    ) or 0

    error_rows = await db.execute(
        select(
            func.split_part(AgentRun.last_error, ":", 1).label("error_type"),
            func.count(AgentRun.id).label("count"),
        )
        .select_from(AgentRun)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(*run_scope, AgentRun.last_error.isnot(None), AgentRun.last_error != "")
        .group_by(text("split_part(agent_runs.last_error, ':', 1)"))
        .order_by(func.count(AgentRun.id).desc())
    )
    error_type_distribution = {
        (row.error_type or "unknown"): int(row.count)
        for row in error_rows.all()
    }

    completion_rate = round((completed_runs / total_runs) if total_runs else 0.0, 4)
    failure_rate = round((failed_runs / total_runs) if total_runs else 0.0, 4)
    retry_success_rate = round((retry_success_runs / retry_triggered_runs) if retry_triggered_runs else 0.0, 4)

    return Response(
        data=AgentMetrics(
            total_runs=total_runs,
            completed_runs=completed_runs,
            failed_runs=failed_runs,
            completion_rate=completion_rate,
            failure_rate=failure_rate,
            retry_triggered_runs=retry_triggered_runs,
            retry_success_runs=retry_success_runs,
            retry_success_rate=retry_success_rate,
            avg_steps_per_run=round(float(avg_steps_per_run or 0), 4),
            error_type_distribution=error_type_distribution,
        )
    )


@router.get("/agent/trend", response_model=Response[list[AgentTrendPoint]])
async def get_agent_trend(
    db: DBSession,
    current_user: CurrentUser,
    days: int = 7,
):
    from datetime import timedelta

    scope = _conversation_scope_filter(current_user)
    start_date = datetime.utcnow() - timedelta(days=days)

    base_rows = await db.execute(
        select(
            cast(AgentRun.created_at, Date).label("date"),
            func.count(AgentRun.id).label("total_runs"),
            func.sum(case((AgentRun.status == "completed", 1), else_=0)).label("completed_runs"),
            func.sum(case((AgentRun.status == "failed", 1), else_=0)).label("failed_runs"),
        )
        .select_from(AgentRun)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(scope, AgentRun.created_at >= start_date)
        .group_by(cast(AgentRun.created_at, Date))
        .order_by(cast(AgentRun.created_at, Date))
    )

    retry_rows = await db.execute(
        select(
            cast(AgentRun.created_at, Date).label("date"),
            func.count(distinct(AgentStep.run_id)).label("retry_runs"),
        )
        .select_from(AgentStep)
        .join(AgentRun, AgentStep.run_id == AgentRun.id)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(
            scope,
            AgentRun.created_at >= start_date,
            AgentStep.step_type == "retry_decision",
        )
        .group_by(cast(AgentRun.created_at, Date))
    )

    retry_map = {str(r.date): int(r.retry_runs or 0) for r in retry_rows.all()}
    points = [
        AgentTrendPoint(
            date=str(r.date),
            total_runs=int(r.total_runs or 0),
            completed_runs=int(r.completed_runs or 0),
            failed_runs=int(r.failed_runs or 0),
            retry_runs=retry_map.get(str(r.date), 0),
        )
        for r in base_rows.all()
    ]
    return Response(data=points)


@router.get("/search", response_model=Response[SearchMetrics])
async def get_search_metrics(
    current_user: CurrentUser,
):
    # stats access follows the same authenticated surface as the existing stats APIs
    del current_user
    try:
        async with httpx.AsyncClient(timeout=settings.search_timeout_sec) as client:
            resp = await client.get(f"{settings.search_service_url}/stats")
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return Response(data=_empty_search_metrics(), msg="search service unavailable")

    return Response(data=SearchMetrics(**payload))


@router.get("/search/trend", response_model=Response[list[SearchTrendPoint]])
async def get_search_trend(
    current_user: CurrentUser,
    days: int = 7,
):
    del current_user
    try:
        async with httpx.AsyncClient(timeout=settings.search_timeout_sec) as client:
            resp = await client.get(f"{settings.search_service_url}/stats/trend", params={"days": days})
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        from datetime import timedelta
        today = datetime.utcnow().date()
        points = [
            SearchTrendPoint(date=str(today - timedelta(days=offset)))
            for offset in range(days - 1, -1, -1)
        ]
        return Response(data=points, msg="search service unavailable")

    return Response(data=[SearchTrendPoint(**item) for item in payload])

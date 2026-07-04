from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AgentRunResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    conversation_id: str
    goal: str
    status: str
    route: Optional[str] = None
    current_step: Optional[str] = None
    next_step: Optional[str] = None
    completed_steps_summary: str = ""
    plan_snapshot: dict = {}
    step_history: list[dict] = []
    artifacts: list[dict] = []
    last_error: Optional[str] = None
    retry_count: int = 0
    budget_remaining: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentStepResponse(BaseModel):
    id: str
    run_id: str
    step_key: str
    step_type: str
    step_goal: str
    status: str
    output: str = ""
    error: str = ""
    tool_trace: list[dict] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

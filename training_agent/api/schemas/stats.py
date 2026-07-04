"""Stats Schemas."""

from pydantic import BaseModel


class UsageStats(BaseModel):
    total_queries: int = 0
    total_messages: int = 0
    avg_latency_ms: int = 0
    today_queries: int = 0
    active_users: int = 0
    avg_tokens: int = 0


class QueryStat(BaseModel):
    query: str
    count: int


class TrendPoint(BaseModel):
    date: str
    count: int


class AgentMetrics(BaseModel):
    total_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    completion_rate: float = 0.0
    failure_rate: float = 0.0
    retry_triggered_runs: int = 0
    retry_success_runs: int = 0
    retry_success_rate: float = 0.0
    avg_steps_per_run: float = 0.0
    error_type_distribution: dict[str, int] = {}


class AgentTrendPoint(BaseModel):
    date: str
    total_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    retry_runs: int = 0


class SearchMetrics(BaseModel):
    requests_total: int = 0
    cache_hits: int = 0
    coalesced_hits: int = 0
    status_ok: int = 0
    status_empty: int = 0
    status_upstream_failed: int = 0
    status_bad_request: int = 0
    fallback_hits: int = 0
    timeouts: int = 0
    upstream_errors: int = 0
    circuit_open_skips: int = 0
    cache_entries: int = 0
    circuit_open_engines: list[str] = []


class SearchTrendPoint(BaseModel):
    date: str
    requests_total: int = 0
    cache_hits: int = 0
    coalesced_hits: int = 0
    status_ok: int = 0
    status_empty: int = 0
    status_upstream_failed: int = 0
    status_bad_request: int = 0
    timeouts: int = 0
    upstream_errors: int = 0

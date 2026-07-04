"""Search Service.

联网搜索服务，封装 OpenSERP API。
提供统一的搜索接口供 Agent 工具调用。
"""

import os
import logging
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENSERP_URL = os.getenv("OPENSERP_URL", "http://openserp:7000")
DEFAULT_ENGINE = os.getenv("SEARCH_DEFAULT_ENGINE", "baidu")
DEFAULT_LIMIT = int(os.getenv("SEARCH_DEFAULT_LIMIT", "5"))
SEARCH_TIMEOUT_SEC = float(os.getenv("SEARCH_TIMEOUT_SEC", "20"))
SEARCH_CACHE_TTL_SEC = int(os.getenv("SEARCH_CACHE_TTL_SEC", "180"))
SEARCH_FAILURE_THRESHOLD = int(os.getenv("SEARCH_FAILURE_THRESHOLD", "3"))
SEARCH_FAILURE_COOLDOWN_SEC = int(os.getenv("SEARCH_FAILURE_COOLDOWN_SEC", "60"))
SEARCH_FALLBACK_ENGINE = os.getenv("SEARCH_FALLBACK_ENGINE", "bing")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
SEARCH_REDIS_DB = int(os.getenv("SEARCH_REDIS_DB", "4"))
ALLOWED_ENGINES = {"google", "bing", "duckduckgo", "baidu", "yandex", "ecosia"}
PERSIST_TREND_DAYS = 35
GLOBAL_STATS_KEY = "search:stats:global"
TREND_KEY_PREFIX = "search:stats:trend:"

_cache: dict[str, tuple[float, "SearchResponse"]] = {}
_failure_state: dict[str, dict[str, float | int]] = {}
_inflight: dict[str, asyncio.Future["SearchResponse"]] = {}
_inflight_lock = asyncio.Lock()
_stats: dict[str, int] = {
    "requests_total": 0,
    "cache_hits": 0,
    "coalesced_hits": 0,
    "status_ok": 0,
    "status_empty": 0,
    "status_upstream_failed": 0,
    "status_bad_request": 0,
    "fallback_hits": 0,
    "timeouts": 0,
    "upstream_errors": 0,
    "circuit_open_skips": 0,
}
_trend_stats: dict[str, dict[str, int]] = {}
_redis_client: Optional[redis.Redis] = None

app = FastAPI(
    title="Search Service",
    description="联网搜索服务，封装 OpenSERP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    engine: str
    rank: int


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    engines_used: list[str]
    took_ms: int
    status: str = "ok"
    cache_hit: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    fallback_engine: Optional[str] = None


class SearchServiceStats(BaseModel):
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


def _cache_key(query: str, engine: str, limit: int, lang: Optional[str]) -> str:
    return f"{engine}:{limit}:{lang or '-'}:{query.strip()}"


def _inc_stat(key: str, value: int = 1) -> None:
    _stats[key] = _stats.get(key, 0) + value
    _schedule_redis_increment(GLOBAL_STATS_KEY, key, value)


def _today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _trend_entry(date_key: str) -> dict[str, int]:
    return _trend_stats.setdefault(
        date_key,
        {
            "requests_total": 0,
            "cache_hits": 0,
            "coalesced_hits": 0,
            "status_ok": 0,
            "status_empty": 0,
            "status_upstream_failed": 0,
            "status_bad_request": 0,
            "timeouts": 0,
            "upstream_errors": 0,
        },
    )


def _inc_trend_stat(key: str, value: int = 1) -> None:
    entry = _trend_entry(_today_key())
    entry[key] = entry.get(key, 0) + value
    _schedule_redis_increment(f"{TREND_KEY_PREFIX}{_today_key()}", key, value, expire_days=PERSIST_TREND_DAYS)


def _prune_trend(days_to_keep: int = 35) -> None:
    cutoff = datetime.utcnow().date() - timedelta(days=days_to_keep - 1)
    stale_keys = []
    for date_key in _trend_stats:
        try:
            if datetime.strptime(date_key, "%Y-%m-%d").date() < cutoff:
                stale_keys.append(date_key)
        except ValueError:
            stale_keys.append(date_key)
    for date_key in stale_keys:
        _trend_stats.pop(date_key, None)


def _schedule_redis_increment(redis_key: str, field: str, value: int, expire_days: int | None = None) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_redis_increment(redis_key, field, value, expire_days))


async def _redis_increment(redis_key: str, field: str, value: int, expire_days: int | None = None) -> None:
    client = _redis_client
    if client is None:
        return
    try:
        await client.hincrby(redis_key, field, value)
        if expire_days:
            await client.expire(redis_key, expire_days * 24 * 3600)
    except Exception as exc:
        logger.warning(f"[Search] redis increment failed key={redis_key} field={field}: {exc}")


async def _load_persisted_stats() -> None:
    client = _redis_client
    if client is None:
        return
    try:
        persisted_stats = await client.hgetall(GLOBAL_STATS_KEY)
        for key, raw_value in persisted_stats.items():
            if key in _stats:
                _stats[key] = int(raw_value or 0)

        today = datetime.utcnow().date()
        for offset in range(PERSIST_TREND_DAYS - 1, -1, -1):
            date_key = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            payload = await client.hgetall(f"{TREND_KEY_PREFIX}{date_key}")
            if not payload:
                continue
            entry = _trend_entry(date_key)
            for key, raw_value in payload.items():
                entry[key] = int(raw_value or 0)
    except Exception as exc:
        logger.warning(f"[Search] redis preload failed: {exc}")


def _get_cached_response(cache_key: str) -> Optional[SearchResponse]:
    cached = _cache.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _cache.pop(cache_key, None)
        return None
    _inc_stat("cache_hits")
    _inc_trend_stat("cache_hits")
    return payload.model_copy(update={"cache_hit": True})


def _set_cached_response(cache_key: str, payload: SearchResponse) -> None:
    if SEARCH_CACHE_TTL_SEC <= 0:
        return
    _cache[cache_key] = (time.time() + SEARCH_CACHE_TTL_SEC, payload)


def _failure_entry(engine: str) -> dict[str, float | int]:
    return _failure_state.setdefault(engine, {"count": 0, "open_until": 0.0})


def _is_circuit_open(engine: str) -> bool:
    entry = _failure_entry(engine)
    open_until = float(entry.get("open_until", 0.0) or 0.0)
    if open_until <= time.time():
        if open_until:
            entry["open_until"] = 0.0
            entry["count"] = 0
        return False
    return True


def _record_success(engine: str) -> None:
    entry = _failure_entry(engine)
    entry["count"] = 0
    entry["open_until"] = 0.0


def _record_failure(engine: str) -> None:
    entry = _failure_entry(engine)
    count = int(entry.get("count", 0) or 0) + 1
    entry["count"] = count
    if count >= SEARCH_FAILURE_THRESHOLD:
        entry["open_until"] = time.time() + SEARCH_FAILURE_COOLDOWN_SEC


def _current_circuit_open_engines() -> list[str]:
    now = time.time()
    return sorted(
        engine
        for engine, entry in _failure_state.items()
        if float(entry.get("open_until", 0.0) or 0.0) > now
    )


async def _query_openserp(
    *,
    query: str,
    engine: str,
    limit: int,
    lang: Optional[str],
) -> tuple[list[SearchResult], list[str], Optional[str], Optional[str]]:
    params = {"text": query, "limit": limit, "format": "json"}
    if lang:
        params["lang"] = lang

    url = f"{OPENSERP_URL}/{engine}/search"
    logger.info(f"[Search] q={query}, engine={engine}, limit={limit}")
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_SEC) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    raw_results = data.get("results", [])
    results = [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("snippet", ""),
            engine=item.get("engine", engine),
            rank=item.get("rank", index + 1),
        )
        for index, item in enumerate(raw_results)
    ]
    engines_used = list({item.engine for item in results}) if results else [engine]
    return results, engines_used, None, None


async def _search_with_fallback(
    *,
    query: str,
    engine: str,
    limit: int,
    lang: Optional[str],
) -> tuple[list[SearchResult], list[str], str, Optional[str], Optional[str]]:
    attempts = [engine]
    fallback_engine = SEARCH_FALLBACK_ENGINE.strip().lower()
    if fallback_engine and fallback_engine != engine and fallback_engine in ALLOWED_ENGINES:
        attempts.append(fallback_engine)

    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    last_fallback_engine: Optional[str] = None

    for current_engine in attempts:
        if _is_circuit_open(current_engine):
            _inc_stat("circuit_open_skips")
            last_error_code = "circuit_open"
            last_error_message = f"search circuit open for engine={current_engine}"
            continue

        try:
            results, engines_used, _, _ = await _query_openserp(
                query=query,
                engine=current_engine,
                limit=limit,
                lang=lang,
            )
            _record_success(current_engine)
            if current_engine != engine:
                last_fallback_engine = current_engine
            return results, engines_used, "ok", None, last_fallback_engine
        except httpx.TimeoutException:
            logger.warning(f"[Search] Timeout calling OpenSERP engine={current_engine}")
            _record_failure(current_engine)
            _inc_stat("timeouts")
            _inc_trend_stat("timeouts")
            last_error_code = "timeout"
            last_error_message = f"search timeout for engine={current_engine}"
        except Exception as exc:
            logger.error(f"[Search] OpenSERP error engine={current_engine}: {exc}")
            _record_failure(current_engine)
            _inc_stat("upstream_errors")
            _inc_trend_stat("upstream_errors")
            last_error_code = "upstream_error"
            last_error_message = str(exc)

    return [], [engine], "upstream_failed", last_error_code, last_fallback_engine


async def _acquire_inflight(cache_key: str) -> tuple[asyncio.Future[SearchResponse], bool]:
    async with _inflight_lock:
        existing = _inflight.get(cache_key)
        if existing is not None:
            return existing, False
        loop = asyncio.get_running_loop()
        future: asyncio.Future[SearchResponse] = loop.create_future()
        _inflight[cache_key] = future
        return future, True


async def _release_inflight(cache_key: str, future: asyncio.Future[SearchResponse]) -> None:
    async with _inflight_lock:
        if _inflight.get(cache_key) is future:
            _inflight.pop(cache_key, None)


@app.on_event("startup")
async def startup():
    global _redis_client
    try:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=SEARCH_REDIS_DB,
            decode_responses=True,
        )
        await _redis_client.ping()
        await _load_persisted_stats()
    except Exception as exc:
        logger.warning(f"[Search] redis unavailable, fallback to memory-only stats: {exc}")
        _redis_client = None
    logger.info(f"Search Service started, OpenSERP URL: {OPENSERP_URL}")


@app.on_event("shutdown")
async def shutdown():
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


@app.get("/health")
async def health_check():
    """Health check."""
    return {
        "status": "ok",
        "openserp_url": OPENSERP_URL,
        "cache_entries": len(_cache),
        "circuit_open_engines": _current_circuit_open_engines(),
    }


@app.get("/stats", response_model=SearchServiceStats)
async def get_stats():
    _prune_trend()
    return SearchServiceStats(
        **_stats,
        cache_entries=len(_cache),
        circuit_open_engines=_current_circuit_open_engines(),
    )


@app.get("/stats/trend", response_model=list[SearchTrendPoint])
async def get_trend(days: int = Query(7, ge=1, le=30)):
    _prune_trend()
    today = datetime.utcnow().date()
    points: list[SearchTrendPoint] = []
    for offset in range(days - 1, -1, -1):
        date_obj = today - timedelta(days=offset)
        date_key = date_obj.strftime("%Y-%m-%d")
        entry = _trend_stats.get(date_key, {})
        points.append(
            SearchTrendPoint(
                date=date_key,
                requests_total=int(entry.get("requests_total", 0)),
                cache_hits=int(entry.get("cache_hits", 0)),
                coalesced_hits=int(entry.get("coalesced_hits", 0)),
                status_ok=int(entry.get("status_ok", 0)),
                status_empty=int(entry.get("status_empty", 0)),
                status_upstream_failed=int(entry.get("status_upstream_failed", 0)),
                status_bad_request=int(entry.get("status_bad_request", 0)),
                timeouts=int(entry.get("timeouts", 0)),
                upstream_errors=int(entry.get("upstream_errors", 0)),
            )
        )
    return points


@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="搜索关键词"),
    engine: str = Query(DEFAULT_ENGINE, description="搜索引擎: google, bing, duckduckgo, baidu, yandex, ecosia"),
    limit: int = Query(DEFAULT_LIMIT, description="结果数量"),
    lang: Optional[str] = Query(None, description="语言代码: EN, ZH, etc."),
):
    """联网搜索。

    调用 OpenSERP API 获取搜索结果。
    """
    _prune_trend()
    _inc_stat("requests_total")
    _inc_trend_stat("requests_total")
    normalized_engine = (engine or DEFAULT_ENGINE).strip().lower()
    if normalized_engine not in ALLOWED_ENGINES:
        _inc_stat("status_bad_request")
        _inc_trend_stat("status_bad_request")
        return SearchResponse(
            query=q,
            results=[],
            engines_used=[],
            took_ms=0,
            status="bad_request",
            error_code="invalid_engine",
            error_message=f"unsupported engine: {engine}",
        )

    if not q.strip():
        _inc_stat("status_empty")
        _inc_trend_stat("status_empty")
        return SearchResponse(query=q, results=[], engines_used=[], took_ms=0, status="empty")

    t0 = time.time()
    cache_key = _cache_key(q, normalized_engine, limit, lang)
    cached = _get_cached_response(cache_key)
    if cached:
        _inc_stat("status_ok" if cached.results else "status_empty")
        return cached.model_copy(update={"took_ms": int((time.time() - t0) * 1000)})

    inflight_future, is_owner = await _acquire_inflight(cache_key)
    if not is_owner:
        _inc_stat("coalesced_hits")
        _inc_trend_stat("coalesced_hits")
        payload = await inflight_future
        _inc_stat("status_ok" if payload.results else "status_empty")
        _inc_trend_stat("status_ok" if payload.results else "status_empty")
        return payload.model_copy(
            update={
                "took_ms": int((time.time() - t0) * 1000),
                "cache_hit": True,
            }
        )

    try:
        results, engines_used, status, error_code, fallback_engine = await _search_with_fallback(
            query=q,
            engine=normalized_engine,
            limit=limit,
            lang=lang,
        )
        took_ms = int((time.time() - t0) * 1000)

        if status == "upstream_failed":
            _inc_stat("status_upstream_failed")
            _inc_trend_stat("status_upstream_failed")
            payload = SearchResponse(
                query=q,
                results=[],
                engines_used=engines_used,
                took_ms=took_ms,
                status=status,
                error_code=error_code,
                error_message="search upstream unavailable",
                fallback_engine=fallback_engine,
            )
            inflight_future.set_result(payload)
            return payload

        payload = SearchResponse(
            query=q,
            results=results,
            engines_used=engines_used,
            took_ms=took_ms,
            status="ok" if results else "empty",
            fallback_engine=fallback_engine,
        )
        if fallback_engine:
            _inc_stat("fallback_hits")
        _inc_stat("status_ok" if results else "status_empty")
        _inc_trend_stat("status_ok" if results else "status_empty")
        _set_cached_response(cache_key, payload)
        inflight_future.set_result(payload)
        logger.info(
            f"[Search] Done: status={payload.status}, results={len(results)}, took_ms={took_ms}, fallback={fallback_engine}"
        )
        return payload
    except Exception as exc:
        if not inflight_future.done():
            inflight_future.set_exception(exc)
        raise
    finally:
        await _release_inflight(cache_key, inflight_future)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)

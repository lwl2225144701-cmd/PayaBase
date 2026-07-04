# Search Optimization Report

Date: 2026-05-18

## Scope

This round focused only on the search path:

- `training_agent/infra/search-service/main.py`
- `training_agent/core/tools/web_search_tool.py`
- `training_agent/core/config.py`
- `training_agent/api/routers/stats.py`
- `web/src/components/stats/stats-page.tsx`

Feishu integration was intentionally left unchanged.

## Goals

1. Stop treating upstream failures as "no results".
2. Add short TTL cache for repeated searches.
3. Add basic circuit-breaker and fallback engine behavior.
4. Prevent same-query concurrent requests from stampeding OpenSERP.
5. Expose search metrics in the main `/stats` page.

## Implementation Changes

### Search service

- Added response fields:
  - `status`
  - `cache_hit`
  - `error_code`
  - `error_message`
  - `fallback_engine`
- Added cache:
  - `SEARCH_CACHE_TTL_SEC`
- Added failure control:
  - `SEARCH_FAILURE_THRESHOLD`
  - `SEARCH_FAILURE_COOLDOWN_SEC`
  - `SEARCH_FALLBACK_ENGINE`
- Added in-flight request coalescing:
  - same `query + engine + limit + lang` only triggers one upstream request
  - concurrent followers wait on the same future
- Added service metrics endpoint:
  - `GET /stats`

### Tool layer

- `WebSearchTool` now distinguishes:
  - `upstream_failed`
  - `bad_request`
  - `empty`
  - `ok`
- Search failure no longer pretends to be "未搜索到相关结果".

### Main backend stats

- Added:
  - `GET /api/stats/search`
- Main backend proxies search metrics from `searchd`.

### Frontend stats page

- Added a new "搜索服务指标" panel to `/stats`.
- Metrics include:
  - request total
  - cache hits
  - coalesced hits
  - cache entries
  - ok / empty / upstream_failed / bad_request
  - fallback hits
  - timeouts
  - upstream errors
  - circuit open skips
  - current circuit open engines

## Config

Added config fields:

- `SEARCH_DEFAULT_ENGINE`
- `SEARCH_DEFAULT_LIMIT`
- `SEARCH_TIMEOUT_SEC`
- `SEARCH_CACHE_TTL_SEC`
- `SEARCH_FAILURE_THRESHOLD`
- `SEARCH_FAILURE_COOLDOWN_SEC`
- `SEARCH_FALLBACK_ENGINE`

Current docker defaults:

- default engine: `baidu`
- fallback engine: `bing`
- timeout: `20s`
- cache ttl: `180s`
- failure threshold: `3`
- cooldown: `60s`

## Validation

### Regression script

Script:

- `training_agent/scripts/search_regression.py`

Checks:

1. `/health` works
2. same query second call returns `cache_hit=true`
3. invalid engine returns `status=bad_request`
4. `/stats` works

### Real run result

Regression result after rebuild:

- first search: `status=ok`
- second search: `cache_hit=true`
- invalid engine: `status=bad_request`
- `/stats`: available

Observed metrics after regression:

- `requests_total=8`
- `cache_hits=1`
- `coalesced_hits=4`
- `status_ok=2`
- `status_bad_request=1`
- `timeouts=0`
- `upstream_errors=0`

### Same-query burst probe

Burst:

- total requests: `10`
- concurrency: `5`
- query: `OpenAI 最新模型`

Observed metrics after burst:

- `requests_total=13`
- `cache_hits=6`
- `coalesced_hits=4`
- `status_ok=12`
- `status_bad_request=1`
- `status_upstream_failed=0`
- `timeouts=0`
- `upstream_errors=0`

## Conclusion

Search is now in a materially better state:

- repeated queries are cached
- same-query concurrency is coalesced
- upstream failures are distinguishable from empty results
- metrics are visible from the main app stats page

## Remaining Work

1. Persist search metrics to Redis or DB if you need restart-safe counters.
2. Add search trend history if you want time-series charts in `/stats`.
3. Add engine-level comparison if you later run mixed `baidu/bing/google` strategies.

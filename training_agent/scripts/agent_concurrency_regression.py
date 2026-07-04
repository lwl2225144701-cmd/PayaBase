#!/usr/bin/env python3
"""Small concurrency regression for Agent run/step stability."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = 240,
) -> tuple[int, str]:
    headers: dict[str, str] = {}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _login(base_url: str, code: str) -> str:
    query = urllib.parse.urlencode({"code": code})
    _, text = _request("POST", f"{base_url}/api/auth/sso?{query}", timeout=30)
    payload = json.loads(text)
    token = payload.get("data", {}).get("access_token")
    if not token:
        raise RuntimeError(f"login missing token: {payload}")
    return token


def _post_json(base_url: str, token: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
    status, text = _request("POST", f"{base_url}{path}", token=token, data=data)
    if status >= 400:
        raise RuntimeError(f"POST {path} failed: {status} {text[:300]}")
    return json.loads(text)


def _get_json(base_url: str, token: str, path: str) -> dict[str, Any]:
    status, text = _request("GET", f"{base_url}{path}", token=token)
    if status >= 400:
        raise RuntimeError(f"GET {path} failed: {status} {text[:300]}")
    return json.loads(text)


def _post_sse(base_url: str, token: str, conversation_id: str, message: str, kb_id: str | None) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"message": message}
    if kb_id:
        payload["knowledge_base_id"] = kb_id
    _, text = _request(
        "POST",
        f"{base_url}/api/conversations/{conversation_id}/chat",
        token=token,
        data=payload,
        timeout=300,
    )
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        raw = line[6:]
        if raw == "[DONE]":
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events


def _agent_meta(events: list[dict[str, Any]]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for event in events:
        if event.get("agent"):
            meta = event["agent"] or {}
    return meta


def run_one(
    base_url: str,
    token: str,
    kb_id: str | None,
    round_idx: int,
    worker_idx: int,
) -> dict[str, Any]:
    started = time.time()
    message = f"请基于知识库回答培训管理制度核心流程。round={round_idx} worker={worker_idx}"
    result: dict[str, Any] = {
        "round": round_idx,
        "worker": worker_idx,
        "ok": False,
        "status": "error",
        "latency_ms": 0,
        "run_id": "",
        "route": "",
        "steps": 0,
        "last_error": "",
        "error": "",
    }
    try:
        conv = _post_json(
            base_url,
            token,
            "/api/conversations",
            {
                "title": f"Agent Concurrency R{round_idx} W{worker_idx}",
                "knowledge_base_id": kb_id,
            },
        )
        conversation_id = conv.get("data", {}).get("id")
        if not conversation_id:
            raise RuntimeError("missing conversation_id")
        events = _post_sse(base_url, token, conversation_id, message, kb_id)
        finished = any(bool(event.get("finished")) for event in events)
        meta = _agent_meta(events)
        run_id = meta.get("run_db_id") or ""
        run_data: dict[str, Any] = {}
        steps: list[dict[str, Any]] = []
        if run_id:
            run_data = _get_json(base_url, token, f"/api/agent/runs/{run_id}").get("data", {}) or {}
            steps = _get_json(base_url, token, f"/api/agent/runs/{run_id}/steps").get("data", []) or []
        result.update(
            {
                "ok": bool(finished and run_id and run_data.get("status") == "completed" and len(steps) >= 2),
                "status": run_data.get("status") or "missing_run",
                "latency_ms": int((time.time() - started) * 1000),
                "run_id": run_id,
                "route": run_data.get("route") or "",
                "steps": len(steps),
                "last_error": (run_data.get("last_error") or "")[:300],
            }
        )
    except Exception as exc:
        result["latency_ms"] = int((time.time() - started) * 1000)
        result["error"] = str(exc)[:300]
    return result


def build_report(results: list[dict[str, Any]], concurrency: int, rounds: int) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    latencies = [int(r.get("latency_ms") or 0) for r in results]
    route_counts: dict[str, int] = {}
    for r in results:
        route = r.get("route") or "unknown"
        route_counts[route] = route_counts.get(route, 0) + 1

    lines = [
        "# Agent 并发回归结果",
        "",
        f"- 生成时间: {now}",
        f"- concurrency: {concurrency}",
        f"- rounds: {rounds}",
        f"- total: {len(results)}",
        f"- success: {len(ok)}",
        f"- failure: {len(failed)}",
    ]
    if latencies:
        lines.extend(
            [
                f"- avg_ms: {int(statistics.mean(latencies))}",
                f"- min_ms: {min(latencies)}",
                f"- max_ms: {max(latencies)}",
            ]
        )
    lines.extend(["", "## 路由分布", ""])
    for route, count in sorted(route_counts.items()):
        lines.append(f"- `{route}`: {count}")
    lines.extend(["", "## 请求明细", ""])
    for r in results:
        marker = "PASS" if r.get("ok") else "FAIL"
        lines.append(
            f"- `{marker}` round={r.get('round')} worker={r.get('worker')} "
            f"status=`{r.get('status')}` route=`{r.get('route')}` steps={r.get('steps')} "
            f"latency_ms={r.get('latency_ms')} run=`{r.get('run_id') or '-'}` "
            f"last_error=`{r.get('last_error') or ''}` error=`{r.get('error') or ''}`"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent concurrency regression.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--login-code", default="admin")
    parser.add_argument("--kb-id", default="")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", default="training_agent/docs/agent-concurrency-regression-last.md")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _login(base_url, args.login_code)
    kb_id = args.kb_id or None
    results: list[dict[str, Any]] = []
    for round_idx in range(1, args.rounds + 1):
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [
                pool.submit(run_one, base_url, token, kb_id, round_idx, worker_idx)
                for worker_idx in range(1, args.concurrency + 1)
            ]
            for future in concurrent.futures.as_completed(futures):
                r = future.result()
                results.append(r)
                marker = "OK" if r.get("ok") else "FAIL"
                print(
                    f"[{marker}] round={r.get('round')} worker={r.get('worker')} "
                    f"status={r.get('status')} route={r.get('route')} steps={r.get('steps')} "
                    f"latency={r.get('latency_ms')}ms"
                )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(build_report(results, args.concurrency, args.rounds))
    print(f"[OK] report generated: {args.output}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

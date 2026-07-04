#!/usr/bin/env python3
"""MVP Agent regression runner.

Covers three minimal paths:
1) RAG QA
2) document summary
3) content generation
4) artifact requests (ppt/pdf)
5) retry/fallback candidate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any


def _request(
    method: str,
    url: str,
    token: str,
    data: dict[str, Any] | None = None,
    timeout: int = 90,
) -> tuple[int, str]:
    body = None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, method=method, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _post_json(base_url: str, token: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    status, text = _request("POST", f"{base_url}{path}", token, data=payload)
    if status >= 400:
        raise RuntimeError(f"POST {path} failed: {status} {text[:300]}")
    return json.loads(text)


def _get_json(base_url: str, token: str, path: str) -> dict[str, Any]:
    status, text = _request("GET", f"{base_url}{path}", token)
    if status >= 400:
        raise RuntimeError(f"GET {path} failed: {status} {text[:300]}")
    return json.loads(text)


def _post_sse_collect(base_url: str, token: str, path: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    status, text = _request("POST", f"{base_url}{path}", token, data=payload, timeout=180)
    if status >= 400:
        raise RuntimeError(f"SSE POST {path} failed: {status} {text[:300]}")

    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        raw = line[6:]
        if raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        events.append(obj)
    return events


def _extract_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    text_parts: list[str] = []
    artifacts: list[dict[str, Any]] = []
    agent_meta: dict[str, Any] = {}
    for e in events:
        if e.get("content"):
            text_parts.append(e["content"])
        if e.get("artifact"):
            artifacts.append(e["artifact"])
        if e.get("agent"):
            agent_meta = e["agent"] or {}
    return {
        "content_preview": ("".join(text_parts)[:200]).replace("\n", " "),
        "artifacts": artifacts,
        "agent": agent_meta,
        "finished": any(bool(e.get("finished")) for e in events),
    }


def _fix_mojibake(text: str) -> str:
    """Try to repair common UTF-8 mojibake like 'æ ¹æ®'."""
    if not text:
        return text
    suspicious = any(ch in text for ch in ("æ", "å", "ç", "ï", "ã", "ð"))
    if not suspicious:
        return text
    try:
        repaired = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        return repaired or text
    except Exception:
        return text


def run_case(base_url: str, token: str, message: str, kb_id: str | None) -> dict[str, Any]:
    conv = _post_json(
        base_url,
        token,
        "/api/conversations",
        {"title": f"MVP Regression {datetime.utcnow().isoformat()[:19]}", "knowledge_base_id": kb_id},
    )
    conversation_id = conv.get("data", {}).get("id")
    if not conversation_id:
        raise RuntimeError(f"create conversation failed: {conv}")

    events = _post_sse_collect(
        base_url,
        token,
        f"/api/conversations/{conversation_id}/chat",
        {"message": message, "knowledge_base_id": kb_id},
    )
    s = _extract_summary(events)

    latest_run = _get_json(base_url, token, f"/api/agent/conversations/{conversation_id}/runs/latest")
    run_data = latest_run.get("data", {})
    run_id = run_data.get("id")
    steps_data: list[dict[str, Any]] = []
    if run_id:
        steps_res = _get_json(base_url, token, f"/api/agent/runs/{run_id}/steps")
        steps_data = steps_res.get("data", []) or []

    return {
        "conversation_id": conversation_id,
        "query": message,
        "sse_summary": s,
        "run": run_data,
        "steps": steps_data,
    }


def build_markdown(cases: list[dict[str, Any]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# MVP Agent 回归结果",
        "",
        f"- 生成时间: {now}",
        "",
        "## 路由覆盖",
        "",
    ]
    route_counts: dict[str, int] = {}
    for c in cases:
        route = ((c.get("run") or {}).get("route")) or "unknown"
        route_counts[route] = route_counts.get(route, 0) + 1
    for route, count in sorted(route_counts.items()):
        lines.append(f"- `{route}`: {count}")
    lines.extend([
        "",
        "## 用例结果",
        "",
    ])
    for idx, c in enumerate(cases, start=1):
        run = c.get("run", {}) or {}
        steps = c.get("steps", []) or []
        sse = c.get("sse_summary", {}) or {}
        preview = _fix_mojibake(sse.get("content_preview", "-"))
        retry_hit = any((st.get("step_type") == "retry_decision") for st in steps)
        lines.extend(
            [
                f"### Case {idx}",
                f"- Query: `{c.get('query', '')}`",
                f"- Conversation: `{c.get('conversation_id', '-')}`",
                f"- Run: `{run.get('id', '-')}` status=`{run.get('status', '-')}` route=`{run.get('route', '-')}`",
                f"- SSE finished: `{sse.get('finished')}` artifacts={len(sse.get('artifacts', []))}",
                f"- Content preview: {preview}",
                f"- Retry step hit: `{retry_hit}`",
                f"- Steps: {len(steps)}",
            ]
        )
        for st in steps:
            lines.append(
                f"  - `{st.get('step_key')}` type=`{st.get('step_type')}` status=`{st.get('status')}` error=`{(st.get('error') or '')[:80]}`"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Run MVP agent regression and generate markdown report.")
    p.add_argument("--base-url", default="http://127.0.0.1:8123", help="API base url")
    p.add_argument("--token", default=os.getenv("MVP_TOKEN", ""), help="Bearer token")
    p.add_argument("--kb-id", default="", help="Optional knowledge_base_id")
    p.add_argument(
        "--output",
        default="training_agent/docs/mvp-agent-regression-last.md",
        help="Markdown output path",
    )
    args = p.parse_args()

    if not args.token:
        print("ERROR: missing token. pass --token or set MVP_TOKEN", file=sys.stderr)
        return 2

    kb_id = args.kb_id or None
    cases_query = [
        "请基于知识库回答：培训管理制度的核心流程是什么？",
        "请总结一下培训管理制度的核心内容。",
        "请输出一份非常完整的方案，如果失败请自动重试并给出可执行结果。",
        "请基于已有资料生成一份培训宣讲PPT大纲，并创建PPT任务。",
        "请基于已有资料生成一份培训总结PDF，并创建PDF任务。",
        "如果本次处理失败，请触发重试并给出降级提示。",
        "[FORCE_AGENT_STEP1_FAIL] 请在失败后自动重试，并输出降级结果。",
    ]
    results: list[dict[str, Any]] = []
    for q in cases_query:
        try:
            results.append(run_case(args.base_url, args.token, q, kb_id))
        except urllib.error.URLError as e:
            print(f"NETWORK ERROR for query={q[:20]}... {e}", file=sys.stderr)
            results.append({"query": q, "conversation_id": "-", "run": {"status": "error"}, "steps": [], "sse_summary": {}})
        except Exception as e:
            print(f"CASE ERROR for query={q[:20]}... {e}", file=sys.stderr)
            results.append({"query": q, "conversation_id": "-", "run": {"status": "error"}, "steps": [], "sse_summary": {}})

    md = build_markdown(results)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] report generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

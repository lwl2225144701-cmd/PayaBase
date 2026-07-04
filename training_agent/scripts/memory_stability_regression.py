#!/usr/bin/env python3
"""Multi-turn memory stability regression for the autonomous Agent.

The goal is to verify that conversation-level context and agent step state
remain stable across multiple turns in the same conversation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from typing import Any


def _request(
    method: str,
    url: str,
    token: str,
    data: dict[str, Any] | None = None,
    timeout: int = 120,
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
    status, text = _request("POST", f"{base_url}{path}", token, data=payload, timeout=240)
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
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events


def _extract_text(events: list[dict[str, Any]]) -> str:
    return "".join(event.get("content", "") for event in events if event.get("content"))


def _extract_agent_meta(events: list[dict[str, Any]]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for event in events:
        if event.get("agent"):
            meta = event["agent"] or {}
    return meta


def _extract_artifacts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for event in events:
        if event.get("artifact"):
            items.append(event["artifact"])
    return items


def _memory_hit(reply_text: str, expected_tokens: list[str]) -> bool:
    if not reply_text:
        return False
    upper = reply_text.upper()
    pos = -1
    for token in expected_tokens:
        idx = upper.find(token.upper(), pos + 1)
        if idx < 0:
            return False
        pos = idx
    return True


def _post_chat(base_url: str, token: str, conversation_id: str, message: str, kb_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message}
    if kb_id:
        payload["knowledge_base_id"] = kb_id
    events = _post_sse_collect(base_url, token, f"/api/conversations/{conversation_id}/chat", payload)
    agent_meta = _extract_agent_meta(events)
    run_id = agent_meta.get("run_db_id")
    run = {}
    steps: list[dict[str, Any]] = []
    if run_id:
        run = _get_json(base_url, token, f"/api/agent/runs/{run_id}").get("data", {}) or {}
        steps = _get_json(base_url, token, f"/api/agent/runs/{run_id}/steps").get("data", []) or []
    return {
        "message": message,
        "text": _extract_text(events),
        "agent": agent_meta,
        "artifacts": _extract_artifacts(events),
        "run": run,
        "steps": steps,
    }


def build_report(turns: list[dict[str, Any]], conversation_id: str) -> str:
    lines = [
        "# Agent 记忆稳定性回归",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- conversation_id: `{conversation_id}`",
        "",
    ]
    for idx, turn in enumerate(turns, start=1):
        run = turn.get("run", {}) or {}
        steps = turn.get("steps", []) or []
        agent = turn.get("agent", {}) or {}
        text = (turn.get("text") or "").replace("\n", " ")
        tokens = turn.get("expected_tokens", []) or []
        hit = _memory_hit(text, tokens) if tokens else False
        lines.extend(
            [
                f"## Turn {idx}",
                f"- Query: `{turn.get('message', '')}`",
                f"- Run: `{run.get('id', '-')}` status=`{run.get('status', '-')}` route=`{run.get('route', '-')}`",
                f"- Agent: status=`{agent.get('status', '-')}` current_step=`{agent.get('current_step', '-')}` next_step=`{agent.get('next_step', '-')}`",
                f"- Reply preview: {text[:220]}",
                f"- Memory hit: `{hit}`",
                f"- Steps: {len(steps)}",
            ]
        )
        for step in steps:
            lines.append(
                f"  - `{step.get('step_key')}` type=`{step.get('step_type')}` status=`{step.get('status')}`"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-turn agent memory stability regression.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--token", default=os.getenv("MVP_TOKEN", ""))
    parser.add_argument("--kb-id", default="")
    parser.add_argument("--output", default="training_agent/docs/memory-stability-regression-last.md")
    args = parser.parse_args()

    if not args.token:
        print("ERROR: missing token", file=sys.stderr)
        return 2

    conv = _post_json(
        args.base_url,
        args.token,
        "/api/conversations",
        {
            "title": f"Memory Stability {datetime.utcnow().isoformat()[:19]}",
            "knowledge_base_id": args.kb_id or None,
        },
    )
    conversation_id = conv.get("data", {}).get("id")
    if not conversation_id:
        raise RuntimeError("failed to create conversation")

    turns = [
        {
            "message": "请记住三个关键词：ALPHA-17、BETA-29、GAMMA-41。先简要说明你已经记住了。",
            "expected_tokens": ["ALPHA-17", "BETA-29", "GAMMA-41"],
        },
        {
            "message": "继续：把刚才的三个关键词按顺序列出来，不要改动顺序。",
            "expected_tokens": ["ALPHA-17", "BETA-29", "GAMMA-41"],
        },
        {
            "message": "再继续：请沿用前两轮的关键词顺序，输出一个简短复盘。",
            "expected_tokens": ["ALPHA-17", "BETA-29", "GAMMA-41"],
        },
    ]

    results: list[dict[str, Any]] = []
    for turn in turns:
        results.append(_post_chat(args.base_url, args.token, conversation_id, turn["message"], args.kb_id or None) | {"expected_tokens": turn["expected_tokens"]})

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(build_report(results, conversation_id))
    print(f"[OK] report generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Direct Mimo API concurrency probe.

This bypasses Agent/RAG/DB and calls the OpenAI-compatible Mimo endpoint
directly, so failures can be attributed to the upstream model service or
network path rather than the application state machine.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return values
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _call_mimo(
    *,
    base_url: str,
    api_key: str,
    model: str,
    worker: int,
    round_idx: int,
    timeout: int,
    prompt_repeat: int,
    max_tokens: int,
    stream: bool,
) -> dict[str, Any]:
    started = time.time()
    result = {
        "round": round_idx,
        "worker": worker,
        "ok": False,
        "latency_ms": 0,
        "status": 0,
        "error_type": "",
        "error": "",
    }
    context = "培训管理制度包括需求调研、计划制定、课程实施、效果评估、复盘改进。"
    long_context = context * max(1, prompt_repeat)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是企业培训助手，请简洁回答。"},
            {
                "role": "user",
                "content": (
                    f"请基于以下资料输出培训管理制度的核心流程和实施建议。"
                    f"round={round_idx} worker={worker}\n\n资料：{long_context}"
                ),
            },
        ],
        "max_completion_tokens": max_tokens,
        "temperature": 0.2,
        "top_p": 0.95,
        "stream": stream,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        method="POST",
        headers={"api-key": api_key, "Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            if stream:
                content_parts: list[str] = []
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if line == "[DONE]":
                        break
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = (((item.get("choices") or [{}])[0].get("delta")) or {})
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                content = "".join(content_parts)
            else:
                data = json.loads(text)
                content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            result.update(
                {
                    "ok": bool(content),
                    "status": resp.status,
                    "latency_ms": int((time.time() - started) * 1000),
                    "error": "" if content else "empty_content",
                }
            )
    except Exception as exc:
        msg = str(exc)
        lowered = msg.lower()
        error_type = "unknown"
        if "timed out" in lowered or "timeout" in lowered:
            error_type = "timeout"
        elif "ssl" in lowered or "eof" in lowered:
            error_type = "ssl_eof"
        elif "429" in lowered or "too many" in lowered:
            error_type = "rate_limit"
        elif "401" in lowered or "403" in lowered or "auth" in lowered:
            error_type = "auth"
        result.update(
            {
                "ok": False,
                "latency_ms": int((time.time() - started) * 1000),
                "error_type": error_type,
                "error": msg[:300],
            }
        )
    return result


def build_report(results: list[dict[str, Any]], concurrency: int, rounds: int) -> str:
    ok = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    latencies = [int(r.get("latency_ms") or 0) for r in results]
    errors: dict[str, int] = {}
    for r in failed:
        key = r.get("error_type") or "unknown"
        errors[key] = errors.get(key, 0) + 1

    lines = [
        "# Mimo 直连并发探测",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
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
    lines.extend(["", "## 错误分布", ""])
    if errors:
        for error_type, count in sorted(errors.items()):
            lines.append(f"- `{error_type}`: {count}")
    else:
        lines.append("- 无")
    lines.extend(["", "## 明细", ""])
    for r in results:
        marker = "PASS" if r.get("ok") else "FAIL"
        lines.append(
            f"- `{marker}` round={r.get('round')} worker={r.get('worker')} "
            f"status={r.get('status')} latency_ms={r.get('latency_ms')} "
            f"error_type=`{r.get('error_type') or ''}` error=`{r.get('error') or ''}`"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Mimo API concurrency directly.")
    parser.add_argument("--env-file", default="training_agent/.env")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--prompt-repeat", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--output", default="training_agent/docs/mimo-concurrency-probe-last.md")
    args = parser.parse_args()

    env_values = _load_env(args.env_file)
    base_url = os.getenv("LLM_CHAT_BASE_URL") or env_values.get("LLM_CHAT_BASE_URL")
    api_key = os.getenv("LLM_CHAT_API_KEY") or env_values.get("LLM_CHAT_API_KEY")
    model = os.getenv("LLM_CHAT_MODEL") or env_values.get("LLM_CHAT_MODEL") or "mimo-v2.5-pro"
    if not base_url or not api_key:
        raise RuntimeError("missing LLM_CHAT_BASE_URL or LLM_CHAT_API_KEY")

    results: list[dict[str, Any]] = []
    for round_idx in range(1, args.rounds + 1):
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [
                pool.submit(
                    _call_mimo,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    worker=worker,
                    round_idx=round_idx,
                    timeout=args.timeout,
                    prompt_repeat=args.prompt_repeat,
                    max_tokens=args.max_tokens,
                    stream=args.stream,
                )
                for worker in range(1, args.concurrency + 1)
            ]
            for future in concurrent.futures.as_completed(futures):
                r = future.result()
                results.append(r)
                marker = "OK" if r.get("ok") else "FAIL"
                print(
                    f"[{marker}] round={r.get('round')} worker={r.get('worker')} "
                    f"latency={r.get('latency_ms')}ms error_type={r.get('error_type')}"
                )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(build_report(results, args.concurrency, args.rounds))
    print(f"[OK] report generated: {args.output}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

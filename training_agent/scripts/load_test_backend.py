#!/usr/bin/env python3
"""Backend load test helper.

Focuses on the chat pipeline, which is the current highest-risk path for
event-loop blocking and service collapse under concurrent access.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


DEFAULT_BASE_URL = "http://127.0.0.1:8123"


@dataclass
class RequestResult:
    worker: int
    ok: bool
    status: int
    latency_ms: int
    error: str = ""
    bytes_read: int = 0


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: dict | None = None,
        timeout: int = 180,
    ) -> tuple[int, bytes]:
        url = f"{self.base_url}{path}"
        headers = {}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def health(self) -> tuple[int, str]:
        status, body = self._request("GET", "/health", timeout=10)
        return status, body.decode("utf-8", errors="replace")

    def login(self, code: str) -> str:
        query = urllib.parse.urlencode({"code": code})
        status, body = self._request("POST", f"/api/auth/sso?{query}", timeout=20)
        if status != 200:
            raise RuntimeError(f"login failed: status={status}, body={body[:200]!r}")
        payload = json.loads(body.decode("utf-8"))
        token = payload.get("data", {}).get("access_token")
        if not token:
            raise RuntimeError(f"login missing token: {payload}")
        return token

    def create_conversation(self, token: str, knowledge_base_id: str | None = None) -> str:
        status, body = self._request(
            "POST",
            "/api/conversations",
            token=token,
            json_body={"title": "load-test", "knowledge_base_id": knowledge_base_id},
            timeout=30,
        )
        if status != 200:
            raise RuntimeError(f"create conversation failed: status={status}, body={body[:200]!r}")
        payload = json.loads(body.decode("utf-8"))
        conv_id = payload.get("data", {}).get("id")
        if not conv_id:
            raise RuntimeError(f"create conversation missing id: {payload}")
        return conv_id

    def chat_once(self, token: str, conversation_id: str, message: str, knowledge_base_id: str | None = None) -> RequestResult:
        started = time.time()
        status = 0
        try:
            status, body = self._request(
                "POST",
                f"/api/conversations/{conversation_id}/chat",
                token=token,
                json_body={"message": message, "knowledge_base_id": knowledge_base_id},
                timeout=240,
            )
            latency_ms = int((time.time() - started) * 1000)
            ok = status == 200 and b"finished" in body
            return RequestResult(
                worker=-1,
                ok=ok,
                status=status,
                latency_ms=latency_ms,
                error="" if ok else body.decode("utf-8", errors="replace")[:300],
                bytes_read=len(body),
            )
        except Exception as exc:  # pragma: no cover - operational path
            latency_ms = int((time.time() - started) * 1000)
            return RequestResult(
                worker=-1,
                ok=False,
                status=status,
                latency_ms=latency_ms,
                error=str(exc),
            )


def run_chat_load(
    client: ApiClient,
    *,
    login_code: str,
    concurrency: int,
    rounds: int,
    knowledge_base_id: str | None,
    message: str,
) -> list[RequestResult]:
    token = client.login(login_code)
    conversation_ids = [
        client.create_conversation(token, knowledge_base_id=knowledge_base_id)
        for _ in range(concurrency)
    ]

    results: list[RequestResult] = []
    for round_idx in range(rounds):
        print(f"[round {round_idx + 1}] start concurrency={concurrency}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            future_map = {}
            for worker_idx, conv_id in enumerate(conversation_ids, start=1):
                future = pool.submit(
                    client.chat_once,
                    token,
                    conv_id,
                    f"{message} [worker={worker_idx}] [round={round_idx + 1}]",
                    knowledge_base_id,
                )
                future_map[future] = worker_idx

            for future in concurrent.futures.as_completed(future_map):
                worker_idx = future_map[future]
                result = future.result()
                result.worker = worker_idx
                results.append(result)
                marker = "OK" if result.ok else "FAIL"
                print(
                    f"  [{marker}] worker={worker_idx} status={result.status} "
                    f"latency={result.latency_ms}ms bytes={result.bytes_read} "
                    f"error={result.error[:120]}"
                )
    return results


def summarize(results: list[RequestResult]) -> dict:
    if not results:
        return {"total": 0, "success": 0, "failure": 0}
    latencies = [r.latency_ms for r in results]
    success = [r for r in results if r.ok]
    failure = [r for r in results if not r.ok]
    return {
        "total": len(results),
        "success": len(success),
        "failure": len(failure),
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "avg_ms": int(statistics.mean(latencies)),
        "p95_ms": int(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PayaBase API backend load test")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--login-code", default="admin")
    parser.add_argument("--scenario", choices=["chat"], default="chat")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--knowledge-base-id", default=None)
    parser.add_argument("--message", default="请简单介绍当前系统的知识库能力")
    args = parser.parse_args()

    client = ApiClient(args.base_url)
    health_status, health_body = client.health()
    print(f"[health-before] status={health_status} body={health_body[:200]}")
    if health_status != 200:
        print("backend health check failed before test", file=sys.stderr)
        return 2

    if args.scenario != "chat":
        print(f"unsupported scenario: {args.scenario}", file=sys.stderr)
        return 2

    results = run_chat_load(
        client,
        login_code=args.login_code,
        concurrency=args.concurrency,
        rounds=args.rounds,
        knowledge_base_id=args.knowledge_base_id,
        message=args.message,
    )
    summary = summarize(results)
    print("[summary]", json.dumps(summary, ensure_ascii=False))

    health_status, health_body = client.health()
    print(f"[health-after] status={health_status} body={health_body[:200]}")
    if health_status != 200:
        print("backend health check failed after test", file=sys.stderr)
        return 1

    return 0 if summary.get("failure", 1) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

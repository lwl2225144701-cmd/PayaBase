#!/usr/bin/env python3
"""Search service regression helper."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8004"


def request_json(base_url: str, path: str, timeout: int = 30) -> tuple[int, dict]:
    url = f"{base_url.rstrip('/')}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(payload)
        except json.JSONDecodeError:
            return exc.code, {"raw": payload}


def print_json(title: str, payload: dict) -> None:
    print(f"[{title}]")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Search service regression helper")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--query", default="OpenAI 最新模型")
    parser.add_argument("--engine", default="baidu")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--lang", default="")
    args = parser.parse_args()

    health_status, health_body = request_json(args.base_url, "/health", timeout=10)
    print_json("health", {"status_code": health_status, "body": health_body})
    if health_status != 200:
        return 2

    params = {
        "q": args.query,
        "engine": args.engine,
        "limit": str(args.limit),
    }
    if args.lang:
        params["lang"] = args.lang

    query_string = urllib.parse.urlencode(params)
    first_status, first_body = request_json(args.base_url, f"/search?{query_string}")
    print_json("search-first", {"status_code": first_status, "body": first_body})

    second_status, second_body = request_json(args.base_url, f"/search?{query_string}")
    print_json("search-second", {"status_code": second_status, "body": second_body})

    invalid_status, invalid_body = request_json(
        args.base_url,
        f"/search?{urllib.parse.urlencode({'q': args.query, 'engine': 'invalid-engine', 'limit': str(args.limit)})}",
    )
    print_json("search-invalid-engine", {"status_code": invalid_status, "body": invalid_body})

    stats_status, stats_body = request_json(args.base_url, "/stats", timeout=10)
    print_json("stats", {"status_code": stats_status, "body": stats_body})

    checks = [
        first_status == 200,
        second_status == 200,
        invalid_status == 200,
        stats_status == 200,
        second_body.get("cache_hit") is True,
        invalid_body.get("status") == "bad_request",
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())

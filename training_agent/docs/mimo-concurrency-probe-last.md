# Mimo 直连并发探测

- 生成时间: 2026-05-17 03:08:27
- concurrency: 5
- rounds: 5
- total: 25
- success: 22
- failure: 3
- avg_ms: 5417
- min_ms: 2913
- max_ms: 7796

## 错误分布

- `unknown`: 3

## 明细

- `PASS` round=1 worker=4 status=200 latency_ms=3478 error_type=`` error=``
- `PASS` round=1 worker=1 status=200 latency_ms=3825 error_type=`` error=``
- `PASS` round=1 worker=5 status=200 latency_ms=4402 error_type=`` error=``
- `FAIL` round=1 worker=3 status=200 latency_ms=6113 error_type=`` error=`empty_content`
- `PASS` round=1 worker=2 status=200 latency_ms=7634 error_type=`` error=``
- `PASS` round=2 worker=1 status=200 latency_ms=3933 error_type=`` error=``
- `PASS` round=2 worker=2 status=200 latency_ms=4120 error_type=`` error=``
- `PASS` round=2 worker=3 status=200 latency_ms=4817 error_type=`` error=``
- `PASS` round=2 worker=4 status=200 latency_ms=4916 error_type=`` error=``
- `PASS` round=2 worker=5 status=200 latency_ms=4916 error_type=`` error=``
- `PASS` round=3 worker=5 status=200 latency_ms=3762 error_type=`` error=``
- `PASS` round=3 worker=1 status=200 latency_ms=4564 error_type=`` error=``
- `PASS` round=3 worker=2 status=200 latency_ms=4729 error_type=`` error=``
- `PASS` round=3 worker=4 status=200 latency_ms=6634 error_type=`` error=``
- `PASS` round=3 worker=3 status=200 latency_ms=7789 error_type=`` error=``
- `PASS` round=4 worker=4 status=200 latency_ms=2913 error_type=`` error=``
- `PASS` round=4 worker=2 status=200 latency_ms=4266 error_type=`` error=``
- `PASS` round=4 worker=1 status=200 latency_ms=6134 error_type=`` error=``
- `PASS` round=4 worker=3 status=200 latency_ms=7492 error_type=`` error=``
- `FAIL` round=4 worker=5 status=200 latency_ms=7796 error_type=`` error=`empty_content`
- `PASS` round=5 worker=4 status=200 latency_ms=5635 error_type=`` error=``
- `PASS` round=5 worker=1 status=200 latency_ms=5743 error_type=`` error=``
- `PASS` round=5 worker=3 status=200 latency_ms=5862 error_type=`` error=``
- `PASS` round=5 worker=2 status=200 latency_ms=6423 error_type=`` error=``
- `FAIL` round=5 worker=5 status=200 latency_ms=7549 error_type=`` error=`empty_content`
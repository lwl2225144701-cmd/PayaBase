# Agent 并发回归结果

- 生成时间: 2026-05-17 03:04:10
- concurrency: 5
- rounds: 5
- total: 25
- success: 15
- failure: 10
- avg_ms: 18471
- min_ms: 4608
- max_ms: 61599

## 路由分布

- `rag_qa`: 25

## 请求明细

- `PASS` round=1 worker=1 status=`completed` route=`rag_qa` steps=2 latency_ms=4608 run=`28a7b92d-07a0-494b-8186-7a970d5f0001` error=``
- `PASS` round=1 worker=3 status=`completed` route=`rag_qa` steps=2 latency_ms=8735 run=`8ea147e2-948b-4fdd-ad03-f39eea18ae0d` error=``
- `PASS` round=1 worker=5 status=`completed` route=`rag_qa` steps=2 latency_ms=10860 run=`20199694-de98-4542-a9d4-08a4e5477d6d` error=``
- `PASS` round=1 worker=4 status=`completed` route=`rag_qa` steps=2 latency_ms=19123 run=`8f3cbc10-e7f5-4172-b272-6628c1701338` error=``
- `PASS` round=1 worker=2 status=`completed` route=`rag_qa` steps=2 latency_ms=25170 run=`d3a3d321-6b33-4531-9038-cfd2fbecf231` error=``
- `PASS` round=2 worker=4 status=`completed` route=`rag_qa` steps=2 latency_ms=11999 run=`307931b6-e11f-453a-beb5-40551c468f74` error=``
- `PASS` round=2 worker=5 status=`completed` route=`rag_qa` steps=2 latency_ms=17614 run=`b49bbcb8-9640-4a90-944c-346a702388b0` error=``
- `PASS` round=2 worker=2 status=`completed` route=`rag_qa` steps=2 latency_ms=17735 run=`c014023e-281b-4c66-b2d6-94a071cb8fe1` error=``
- `PASS` round=2 worker=1 status=`completed` route=`rag_qa` steps=2 latency_ms=19153 run=`925de9cf-7aa6-494f-a43d-3cdf2987558a` error=``
- `PASS` round=2 worker=3 status=`completed` route=`rag_qa` steps=2 latency_ms=21991 run=`6a382788-294c-4da0-9ca4-b3b33928c22f` error=``
- `PASS` round=3 worker=4 status=`completed` route=`rag_qa` steps=2 latency_ms=7068 run=`de084220-3d8d-47a0-8713-d1d265fc19a2` error=``
- `PASS` round=3 worker=3 status=`completed` route=`rag_qa` steps=2 latency_ms=12035 run=`2241fb22-704a-499c-a3f0-aa72c7e342f4` error=``
- `PASS` round=3 worker=1 status=`completed` route=`rag_qa` steps=2 latency_ms=14812 run=`8c0de324-f532-4210-addb-39512709ac2d` error=``
- `PASS` round=3 worker=5 status=`completed` route=`rag_qa` steps=2 latency_ms=18483 run=`d2b8f5c8-3550-450e-aef2-bca0e4b93cce` error=``
- `FAIL` round=3 worker=2 status=`failed` route=`rag_qa` steps=2 latency_ms=61599 run=`01c2af51-9679-41c1-bd7b-8eedecfe99a9` error=``
- `FAIL` round=4 worker=1 status=`failed` route=`rag_qa` steps=2 latency_ms=15834 run=`672d0762-02c3-4119-8741-8f7587b0beed` error=``
- `FAIL` round=4 worker=5 status=`failed` route=`rag_qa` steps=2 latency_ms=15909 run=`605ce8a3-a1d1-4ad3-a90e-e5c2ed620f22` error=``
- `FAIL` round=4 worker=2 status=`failed` route=`rag_qa` steps=2 latency_ms=15924 run=`c504cf4a-780e-45f8-b69a-56fba833e3f0` error=``
- `FAIL` round=4 worker=4 status=`failed` route=`rag_qa` steps=2 latency_ms=15997 run=`deb136df-3d25-4ce2-a54d-ff3cca6a58c8` error=``
- `FAIL` round=4 worker=3 status=`failed` route=`rag_qa` steps=2 latency_ms=31683 run=`9bc59d2d-26b9-4282-8e8b-3b64d2e53c84` error=``
- `FAIL` round=5 worker=3 status=`failed` route=`rag_qa` steps=2 latency_ms=15926 run=`eed0f586-8ef7-4132-9625-548bae3ccad8` error=``
- `FAIL` round=5 worker=2 status=`failed` route=`rag_qa` steps=2 latency_ms=15964 run=`b9c3652d-eb33-4cdd-b8c8-e2e0e1948ffc` error=``
- `FAIL` round=5 worker=4 status=`failed` route=`rag_qa` steps=2 latency_ms=15963 run=`a4b0edeb-008e-43d1-b18a-7bcf0378e872` error=``
- `FAIL` round=5 worker=1 status=`failed` route=`rag_qa` steps=2 latency_ms=16009 run=`d0688983-c01c-49b4-9e45-5fd9b70698c3` error=``
- `PASS` round=5 worker=5 status=`completed` route=`rag_qa` steps=2 latency_ms=31587 run=`d75d5c81-cee3-430b-be9c-51e570574ffb` error=``
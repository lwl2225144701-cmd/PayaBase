# Agent MVP 最终验收结论

- 生成时间: 2026-05-17
- 验收范围: MVP 1 到 MVP 5
- 后端地址: `http://127.0.0.1:8123`
- 测试知识库: `50ac57ac-ed68-4694-ba13-c1477bd6033f`

## 1. 总体结论

Agent MVP 主功能已完成，MVP 1 到 MVP 5 都已有实现与回归证据。

当前可验收项：
- 单一 Agent 主链路已接入 `chat`
- `AgentRun/AgentStep` 状态持久化已生效
- 前端 RunID 明细、tool trace、stats 指标与趋势已接入
- RAG、文档总结、内容生成、PPT、PDF、retry/fallback 已进入同一 Agent 状态机
- 多轮会话记忆稳定性已有三轮回归证据

已关闭的稳定性问题：
- 初次 5 轮并发回归中，25 条请求通过 15 条、失败 10 条
- 排查后确认不是纯 Mimo 并发问题：Mimo 直连 stream/非 stream 长 prompt 5x5 均通过
- 根因是应用普通聊天链路携带完整历史消息，随着同一会话多轮压测导致 prompt 膨胀
- 已将普通聊天链路历史窗口限制为最近 6 条消息
- 修复后 5 轮并发回归 25/25 通过

## 2. MVP 状态

| MVP | 内容 | 状态 | 证据 |
| --- | --- | --- | --- |
| MVP 1 | 方案型任务闭环 | Done | `mvp-agent-regression-last.md` |
| MVP 2 | 记忆稳定性 | Done | `memory-stability-regression-last.md` |
| MVP 3 | PPT/PDF 产物链路 | Done | `mvp-agent-regression-last.md` |
| MVP 4 | 多步规划与 retry/fallback | Done | 强制失败用例命中 `retry-1` |
| MVP 5 | 通用化收敛 | Done | 全路线回归覆盖主能力 |

## 3. 回归证据

### 3.1 全路线回归

文件: `training_agent/docs/mvp-agent-regression-last.md`

覆盖路由：
- `rag_qa`
- `document_summary`
- `content_generation`
- `ppt_generation`
- `pdf_generation`
- `retry_decision`

关键结果：
- `ppt_generation` 返回 `artifacts=1`
- `pdf_generation` 返回 `artifacts=1`
- 强制失败后命中 `retry_decision`
- 所有主能力都有 `AgentRun/AgentStep`

修复记录：
- 第五轮发现“生成培训总结PDF”先命中 `document_summary`
- 已修复 `RequestRouter` 优先级：`pdf_generation/ppt_generation` 优先于 `document_summary`

### 3.2 记忆稳定性回归

文件: `training_agent/docs/memory-stability-regression-last.md`

结果：
- 三轮同会话测试均 `Memory hit=True`
- 关键词顺序跨轮保持
- 每轮均产生完整 `AgentRun/AgentStep`

### 3.3 并发回归

首次失败报告: `training_agent/docs/agent-concurrency-regression-last.md`

修复后报告: `training_agent/docs/agent-concurrency-regression-after-history-window.md`

配置：
- concurrency: `5`
- rounds: `5`
- total: `25`

首次结果：
- success: `15`
- failure: `10`
- avg_ms: `18471`
- max_ms: `61599`

修复后结果：
- success: `25`
- failure: `0`
- avg_ms: `13802`
- max_ms: `28217`

失败原因抽样：
- `timeout: HTTPSConnectionPool(host='api.xiaomimimo.com', port=443): Read timed out`
- `upstream: HTTPSConnectionPool(host='api.xiaomimimo.com', port=443): Max retries exceeded`
- `SSLEOFError: UNEXPECTED_EOF_WHILE_READING`

判断：
- 失败请求均完整落了 `AgentRun/AgentStep`，状态机没有丢状态
- Mimo 直连并发验证通过，排除“单纯 Mimo 并发不可用”
- 应用侧完整历史回灌导致 prompt 逐轮膨胀，是主要触发因素
- 限制历史窗口后，5x5 并发回归通过

## 4. 当前风险

1. 长会话上下文膨胀风险

影响：
- 如果未来某些链路重新携带完整历史，仍可能导致 LLM 请求超时或连接异常
- 当前普通聊天链路已限制最近 6 条历史消息

建议：
- 将历史窗口大小抽成配置项
- 对历史消息做摘要化，而不是长期拼接原文
- 保留 Mimo 直连探测脚本，后续区分“上游失败”和“应用 prompt 膨胀”

2. 并发报告可读性需要持续保留

已补：
- `agent_concurrency_regression.py` 已新增 `last_error` 字段输出

建议：
- 后续并发报告继续保留 `last_error`、`route`、`steps` 和 `run_id`

## 5. 验收结论

功能 MVP: 通过。

理由：
- MVP 1-5 主能力均已实现
- 单轮全路线回归通过
- 多轮记忆回归通过
- retry/fallback 可控失败回归通过
- 前后端可观测链路可用

稳定性验收: 通过。

理由：
- 修复历史窗口后，5 并发 5 轮共 25 条请求全部通过
- 每条请求都有完整 `AgentRun/AgentStep`
- Mimo 直连 stream/非 stream 探测通过，应用侧主要风险已定位并修复

## 6. 下一步建议

1. 将聊天历史窗口大小配置化。
2. 增加历史摘要机制，减少长会话 token 膨胀。
3. 定期执行 `mimo_concurrency_probe.py` 与 `agent_concurrency_regression.py`，区分上游稳定性和应用链路稳定性。

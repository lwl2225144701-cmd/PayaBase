# 单一自治 Agent 方案与 MVP 拆分 v3

## Summary
把 `ReActAgent` 重命名为 `AgentStepExecutor`，并把它严格收窄成“步骤级执行内核”。  
为了解决“模型做着做着就忘了下一步”的问题，自治系统必须引入**显式步骤状态**、**计划快照**、**已完成步骤摘要**、**下一步指令**和**每步结果回写**，让模型每一轮都只看当前该做什么，而不是自己凭上下文硬猜。

## Key Changes
- 重命名与职责收窄：
  - `ReActAgent` -> `AgentStepExecutor`
  - 只负责单步内的多工具推理、工具调用、结果回写
  - 不负责全局规划、不负责 run 控制、不负责长期记忆
- 新增自治总控层：
  - `AgentOrchestrator`：运行入口与生命周期管理
  - `AgentPlanner`：生成初始计划和可重规划计划
  - `AgentRunner`：按步骤推进，驱动 `AgentStepExecutor`
  - `AgentState`：保存 run / step / artifact / error / memory
  - `AgentPolicy`：步数、超时、重试、白名单、预算
- 解决“忘记下一步”的核心机制：
  - 每一步都显式传入 `current_step`
  - 每一步都显式传入 `next_step`
  - 每一步都显式传入 `completed_steps_summary`
  - 每一步都显式传入 `plan_snapshot`
  - 每一步结果都必须回写到 `AgentState`
  - 每一步结束后由 `Runner` 重新计算“现在应该做什么”
- 现有能力整体内化：
  - `RequestRouter` 规则保留，但只作为 Agent 内部能力复用
  - RAG、方案生成、PPT、PDF、内容生成全部仍然作为工具存在
  - `ToolRegistry` 保持统一接入
- 顶层入口收敛：
  - 对外只保留一条 Agent 主流程
  - 旧的对外路由链路不再作为第二套体系并行存在

## Internal Memory Design
### 1. 每个 run 必须保存的状态
- `goal`
- `status`
- `plan_snapshot`
- `current_step`
- `next_step`
- `completed_steps`
- `completed_steps_summary`
- `step_history`
- `artifacts`
- `last_error`
- `retry_count`
- `budget_remaining`
- `started_at`
- `updated_at`
- `completed_at`

### 2. 每个 step 必须保存的状态
- `step_id`
- `step_type`
- `step_goal`
- `input_context`
- `expected_output`
- `tool_calls`
- `tool_results`
- `step_status`
- `failure_reason`
- `next_action`

### 3. 每轮执行前必须组装的上下文
- 当前用户目标
- 当前计划快照
- 已完成步骤摘要
- 当前步骤目标
- 当前步骤允许使用的工具
- 当前步骤的输出要求
- 本轮预算和停止条件

### 4. 每轮执行后必须写回的内容
- 当前步骤结果
- 工具结果
- 是否成功
- 是否需要重试
- 是否需要重规划
- 下一步建议
- 是否生成产物

## Execution Contract
`AgentStepExecutor` 每次只处理一个明确的 step，不能把整个 run 的责任都压在一次 prompt 里。

### 进入 step 前
Runner 必须传入：
- `goal`
- `plan_snapshot`
- `completed_steps_summary`
- `current_step`
- `step_constraints`
- `available_tools`

### step 执行时
Executor 必须被要求：
- 只围绕当前 step 工作
- 不重新解释整个任务
- 不跳步
- 不自作主张扩展范围
- 如果信息不足，返回“需要补充什么”而不是自己乱推

### step 执行后
必须返回结构化结果：
- `status: success|retry|replan|fail`
- `output`
- `tool_trace`
- `next_step_hint`
- `artifact_refs`
- `memory_patch`

## MVP Split
### MVP 1: 方案型任务闭环
目标：先让 Agent 记得自己在做什么，稳定完成方案型任务。

- 入口层：
  - `chat` 入口不变
  - 所有请求先进入新 Agent
  - 先只覆盖方案型复杂任务
- 自治层：
  - 新增 `AgentOrchestrator`
  - 新增 `AgentPlanner`
  - 先只做一次计划，不做复杂重规划
- 执行层：
  - `AgentStepExecutor` 复用现有多工具推理逻辑
  - 每步强制传入 `current_step`、`next_step`、`completed_steps_summary`
- 输出层：
  - 先返回结构化 Markdown 方案
  - 不强制接 PPT / PDF
- 验收标准：
  - 能自动生成方案
  - 能复用现有检索与方案生成能力
  - 每一步都能记住自己在做哪一步

### MVP 2: 增强记忆稳定性
目标：解决“上下文变长后忘记前文”的问题。

- 引入 `plan_snapshot` 和 `step_history`
- 每一步只带必要摘要，不把完整历史全塞进 prompt
- 增加 `completed_steps_summary`
- 每完成一步就压缩成短记忆，供下一步使用
- 验收标准：
  - 步骤多一点时仍能保持上下文连续
  - 不会因为聊天内容变长而丢失前一步结果

### MVP 3: 产物链路接入
目标：在方案型闭环上补产物输出。

- 增加产物决策：
  - Agent 内部决定是否继续生成 PPT / PDF
- 接入现有异步工具：
  - `ppt_generation`
  - `pdf_export`
- 结果统一：
  - 输出里带 `task_id`
  - 前端能轮询任务状态
- 验收标准：
  - 同一主链路可生成方案、PPT、PDF
  - 任务失败可回收，不阻断整体流程

### MVP 4: 多步规划
目标：让 Agent 能根据每步结果决定下一步，而不是固定流程。

- `AgentPlanner` 输出可变步骤
- 允许基于检索结果插入补检索、补总结步骤
- 新增 `agent_runs` / `agent_steps`
- 每步执行后落状态
- 验收标准：
  - Agent 能根据资料充足程度调整路径
  - 中断后可恢复
  - 执行过程可追踪

### MVP 5: 通用化收敛
目标：把更多原有能力统一纳入同一个 Agent。

- 接入知识问答、文档总结、内容生成
- 内部复用现有 `RequestRouter` 规则
- 对外仍只保留一条主链路
- 验收标准：
  - 全量能力统一进入同一 Agent
  - 前端只看一个任务流，不再区分两套体系

## MVP Status (2026-05-17)
- MVP 1（方案型任务闭环）：`Done`
  - 证据：`mvp-agent-regression-last.md` Case 1/3 `status=completed`
- MVP 2（记忆稳定性）：`Done`
  - 已完成：`current_step/next_step/completed_steps_summary/plan_snapshot/step_history` 持久化链路
  - 已验证：`memory-stability-regression-last.md` 三轮会话均 `Memory hit=True`
  - 备注：后续仍可补长会话与高并发压力样本，但当前 MVP 证据已足够
- MVP 3（产物链路接入）：`Done`
  - 证据：Case 2 `route=ppt_generation`，`artifacts=1`
- MVP 4（多步规划）：`Done (MVP scope)`
  - 证据：Case 5 强制失败注入后，`step-1 failed -> retry-1(retry_decision) success`
  - 说明：当前是最小多步闭环（执行步 + follow-up 步），复杂重规划仍可后续增强
- MVP 5（通用化收敛）：`Done`
  - 已完成：统一 chat 主入口、状态可观测、Agent 指标与趋势面板
  - 已验证：`mvp-agent-regression-last.md` 覆盖 `rag_qa/document_summary/content_generation/ppt_generation/pdf_generation/retry_decision`
  - 修复记录：第五轮回归发现“总结PDF”先命中 `document_summary`，已将 `pdf_generation/ppt_generation` 规则优先级提高到 `document_summary` 之前
  - 备注：后续仍可补并发压测下的统一状态机证据，但当前 MVP5 功能面已闭环

## Test Plan
- 重命名验证：
  - `ReActAgent` 替换为 `AgentStepExecutor` 后，步骤执行行为不回退
- 记忆测试：
  - 多步骤任务中，确认 `completed_steps_summary` 和 `next_step` 能持续正确传递
  - 确认模型不会偏离当前 step 的目标
- MVP 1 回归：
  - 方案型任务闭环能跑通
  - 检索与方案生成能力可复用
- MVP 3 回归：
  - PPT / PDF 任务能正常提交并返回任务 ID
- MVP 4 回归：
  - 动态规划、状态持久化、恢复执行能工作
- MVP 5 回归：
  - RAG、文档总结、内容生成、PPT、PDF、retry/fallback 全路线进入同一个 Agent run/step 状态机

## Assumptions
- `AgentStepExecutor` 只承担步骤执行职责，不承担全局编排。
- 记忆稳定性必须通过显式状态传递来实现，不能只靠长上下文堆积。
- `RequestRouter` 不删除，但只作为新 Agent 的内部能力复用。
- 第一阶段先做方案型任务闭环，再逐步扩展到产物和通用场景。

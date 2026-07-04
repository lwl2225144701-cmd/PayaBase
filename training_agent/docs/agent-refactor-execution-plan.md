# 自治 Agent 改造执行计划

## 目标

把现有已测通的请求能力统一收进一个自治 Agent，对外只保留一条主链路，并按阶段逐步替换内部编排逻辑，避免一次性大改。

## 执行原则

- 先骨架，后能力。
- 先稳定记忆，再扩大场景。
- 先方案闭环，再接产物。
- 先可回退，再扩自治范围。

## 阶段 1：搭骨架

### 目标

先把自治 Agent 的最小运行结构建立起来，能接住一次完整 run。

### 改造内容

- 新增 `AgentOrchestrator`
- 新增 `AgentPlanner`
- 新增 `AgentRunner`
- 新增 `AgentState`
- 新增 `AgentPolicy`
- 将 `ReActAgent` 重命名为 `AgentStepExecutor`

### 输出物

- 一个自治 Agent 总控入口
- 一个步骤执行器
- 一个运行状态对象
- 一个可执行的最小计划

### 验收点

- 能创建 run
- 能生成初始 plan
- 能执行第一步
- 能把步骤结果写回状态

## 阶段 2：稳定记忆

### 目标

解决“做着做着忘记下一步”的问题。

### 改造内容

- 每步显式传入 `current_step`
- 每步显式传入 `next_step`
- 每步显式传入 `completed_steps_summary`
- 每步显式传入 `plan_snapshot`
- 每步结束后写回 `step_history`
- 增加 run/step 持久化

### 输出物

- 可持续的步骤记忆
- 可恢复的运行状态
- 可追踪的步骤历史

### 验收点

- 多步任务不会跑偏
- 步骤之间的上下文连续
- 中断后可以恢复执行

## 阶段 3：方案闭环

### 目标

先把方案型复杂任务跑通，作为 MVP 主链路。

### 改造内容

- 方案型请求统一进入自治 Agent
- 复用 `RequestRouter` 作为内部动作选择能力
- 复用知识检索
- 复用方案生成工具
- 让 `AgentStepExecutor` 在单步内完成检索 + 生成

### 输出物

- 一条方案型任务闭环
- 一条稳定的结构化方案输出链路

### 验收点

- 用户输入方案型目标后，Agent 能自动完成
- 能返回结构化 Markdown 结果
- 能解释失败原因

## 阶段 4：产物接入

### 目标

在方案闭环基础上接入 PPT / PDF。

### 改造内容

- 接入 `ppt_generation`
- 接入 `pdf_export`
- 在自治 Agent 内部决定是否提交产物任务
- 统一返回 `task_id`
- 前端支持任务轮询

### 输出物

- 方案 + PPT
- 方案 + PDF
- 统一任务状态回传

### 验收点

- 产物任务能提交
- 产物任务失败不阻断主链路
- 前端能看到任务进度

## 阶段 5：通用化

### 目标

把知识问答、文档总结、内容生成逐步收进同一个 Agent。

### 改造内容

- 把现有 `RequestRouter` 规则内部化
- 扩展 Agent 的任务类型识别
- 支持更多步骤组合
- 保持统一入口不变

### 输出物

- 通用自治 Agent
- 单一主链路

### 验收点

- 更多请求类型可以进同一个 Agent
- 对外不再保留两套并行业务体系

## 文件级落点

### 入口层

- `api/routers/chat.py`

### 自治层

- `core/agent/orchestrator.py`
- `core/agent/planner.py`
- `core/agent/runner.py`
- `core/agent/state.py`
- `core/agent/policy.py`

### 步骤执行层

- `core/agent/executor.py`

### Prompt 层

- `core/prompts/agent.py`

### 工具层

- `core/tools/registry.py`
- `core/tools/knowledge_tool.py`
- `core/tools/solution_tool.py`
- `core/tools/ppt_tool.py`
- `core/tools/pdf_export_tool.py`

### 路由复用层

- `core/agent/request_router.py`

## 关键风险

- 上下文太长导致步骤记忆丢失
- 计划和执行耦合太深
- 产物任务把主链路卡住
- 状态回写不完整导致恢复失败

## 风险控制

- 每步只传必要摘要
- 计划和执行分层
- 产物异步化
- 每步落状态
- 失败时可回退

## 最终交付标准

- 一条自治 Agent 主链路
- 一套稳定的步骤记忆机制
- 一套方案闭环
- 一套 PPT / PDF 产物链路
- 一套可扩展到更多任务类型的执行框架

## 阶段状态（2026-05-17）

- 阶段 1（搭骨架）：`Done`
- 阶段 2（稳定记忆）：`Done (Base)` / `Pending (Stress Evidence)`
- 阶段 3（方案闭环）：`Done`
- 阶段 4（产物接入）：`Done`
- 阶段 5（通用化）：`Done`

### 当前回归证据
- 文件：`training_agent/docs/mvp-agent-regression-last.md`
- 关键结果：
  - RAG/PPT/内容生成主链路均 `completed`
  - 强制失败注入用例命中 `retry_decision`：`step-1 failed -> retry-1 success`
  - 第五轮全路线回归覆盖 `rag_qa/document_summary/content_generation/ppt_generation/pdf_generation/retry_decision`
  - 发现并修复路由优先级问题：PDF/PPT 产物意图优先于总结意图
- 文件：`training_agent/docs/memory-stability-regression-last.md`
- 关键结果：
  - 三轮同会话回归均 `Memory hit=True`
  - 说明会话级记忆和多轮上下文传递已可用

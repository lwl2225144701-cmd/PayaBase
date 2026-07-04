# 自治 Agent 工程实现清单

## 目标

把当前已经测通的完整请求能力收进一个新的自治 Agent，对外只保留一条主链路：

`用户输入 -> 新自治 Agent -> 结果 -> 前端`

现有 `RequestRouter`、RAG、方案生成、PPT、PDF、内容生成都保留，但它们要变成自治 Agent 内部的能力，不再作为两套体系对外并行存在。

## 现状基线

- `api/routers/chat.py` 目前仍然是主入口。
- `core/agent/executor.py` 里的 `ReActAgent` 已经具备多工具推理能力，但它不是总控。
- `core/tools/registry.py` 和 `BaseTool` 已经提供了统一工具接入方式。
- `core/agent/request_router.py` 已经有规则化请求路由能力。
- `ppt/pdf` 已经是异步产物任务模式，可以继续复用。

## 工程实现拆分

### 1. 入口层

修改：

- `api/routers/chat.py`

目标：

- 保留现有聊天会话、附件、历史消息、流式返回逻辑。
- 不再直接决定“走哪条固定链路”。
- 将最终编排交给新自治 Agent 总控层。

实现要求：

- 入口只做会话校验、消息保存、附件解析、上下文准备。
- 入口把请求交给 `AgentOrchestrator`。
- 入口只负责把最终结果流式返回给前端。

### 2. 自治总控层

新增：

- `core/agent/orchestrator.py`
- `core/agent/planner.py`
- `core/agent/runner.py`
- `core/agent/state.py`
- `core/agent/policy.py`

职责：

- `AgentOrchestrator`
  - 自治任务总入口
  - 管 run 生命周期
  - 决定是否继续、重规划、终止
- `AgentPlanner`
  - 生成初始计划
  - 在需要时生成重规划计划
  - 输出步骤序列和步骤依赖
- `AgentRunner`
  - 逐步执行计划
  - 维护当前步骤、下一步、已完成步骤摘要
  - 调用步骤级执行器
- `AgentState`
  - 保存 run/step/artifact/error/memory
  - 支持恢复、审计、查询
- `AgentPolicy`
  - 限制步数
  - 限制总时长
  - 限制重试次数
  - 限制工具白名单
  - 决定失败回退策略

### 3. 步骤执行层重命名

修改：

- `core/agent/executor.py`

动作：

- 将 `ReActAgent` 重命名为 `AgentStepExecutor`

新职责：

- 只处理单个 step 内的多工具推理
- 只负责调用工具、读取结果、回写步骤结果
- 不负责全局规划
- 不负责 run 控制
- 不负责长期记忆

保留能力：

- 工具调用循环
- tool result 回写
- PPT/PDF task_id 追踪

### 4. 记忆与状态

新增状态模型字段：

run 级：

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

step 级：

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

新增：

- `models/tables.py` 或对应迁移文件里的 agent run/step 表
- `api/schemas/agent.py` 或对应响应 schema

要求：

- 每一步执行后都必须写回状态
- 下一步只读必要摘要，不依赖完整长上下文
- 中断后能恢复

### 5. Prompt 与上下文

修改：

- `core/prompts/agent.py`
- 必要时补 `core/agent/prompt.py`

要求：

- 新增步骤执行 prompt
- 每轮执行前显式传入：
  - `goal`
  - `plan_snapshot`
  - `current_step`
  - `next_step`
  - `completed_steps_summary`
  - `available_tools`
- 每轮执行后显式返回：
  - `status`
  - `output`
  - `tool_trace`
  - `next_step_hint`
  - `artifact_refs`
  - `memory_patch`

### 6. 工具层复用

保留：

- `core/tools/registry.py`
- `core/tools/base.py`
- `core/tools/knowledge_tool.py`
- `core/tools/solution_tool.py`
- `core/tools/ppt_tool.py`
- `core/tools/pdf_export_tool.py`
- 其他现有工具

要求：

- 工具不重写业务逻辑
- 工具继续通过 `ToolRegistry` 接入
- 自治 Agent 只依赖统一工具接口

### 7. 路由规则内化

保留但下沉：

- `core/agent/request_router.py`

调整定位：

- 不再作为对外顶层分流器
- 作为自治 Agent 内部的“动作选择 / 步骤判断”能力复用

### 8. 前端与产物

修改：

- 现有 chat 页面和状态展示相关组件

要求：

- 前端能看到自治步骤
- 前端能看到当前步骤、已完成步骤、产物任务 ID、失败原因
- PPT / PDF 仍沿用异步任务模型

## MVP 顺序

### MVP 1

目标：

- 先跑通方案型任务闭环

内容：

- `AgentOrchestrator`
- `AgentPlanner`
- `AgentStepExecutor`
- `AgentState`
- `goal -> 检索 -> 方案生成 -> 返回`

验收：

- 能稳定生成方案
- 能记住当前步骤

### MVP 2

目标：

- 解决“做着做着忘了下一步”

内容：

- `plan_snapshot`
- `completed_steps_summary`
- `step_history`
- 每步状态回写

验收：

- 多步任务不中途跑偏
- 步骤上下文连续

### MVP 3

目标：

- 接入产物链路

内容：

- PPT
- PDF
- 产物 task_id 统一返回

验收：

- 可提交异步任务
- 失败可回收

### MVP 4

目标：

- 支持多步规划和补步骤

内容：

- 动态重规划
- 补检索
- 补总结

验收：

- Agent 可根据资料情况调整路径

### MVP 5

目标：

- 收敛到通用自治 Agent

内容：

- 知识问答
- 文档总结
- 内容生成
- 现有路由规则内部化

验收：

- 对外只保留一条主链路
- 不再有两套并行业务体系

## 依赖顺序

1. 先做 `AgentStepExecutor` 重命名和接口稳定
2. 再做 `AgentOrchestrator` / `Planner` / `Runner`
3. 再做 `AgentState` / `AgentPolicy`
4. 再补 prompt 和上下文回写
5. 再接 PPT / PDF
6. 最后扩展到更多通用场景

## 测试清单

- 入口测试
- 步骤记忆测试
- 方案闭环测试
- 产物测试
- 护栏测试
- 恢复测试

## 交付标准

- 单一自治 Agent 入口可用
- 方案型任务可稳定闭环
- 多步执行不会忘记下一步
- 产物任务可正常提交
- 失败可回退，状态可恢复

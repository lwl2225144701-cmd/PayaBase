# Chat Pipeline 拆分冒烟测试清单

> 重构后各模块独立验证清单，确保拆分未破坏原有功能。

## 模块清单

| 模块 | 文件 | 职责 |
|------|------|------|
| 路由初始化 | `routing_flow.py` | 请求路由 + AgentRun 初始化 |
| RAG 检索 | `rag_flow.py` | 知识库检索 + 上下文注入 |
| 普通回答 | `answer_flow.py` | LLM 流式回答生成 |
| Autonomous Agent | `autonomous_flow.py` | 工具调用 + Agent 步骤执行 |
| Artifact 生成 | `artifact_flow.py` | PPT/PDF 生成 |
| Retry/Finalize | `finalize_flow.py` | 重试逻辑 + Agent 结果 finalize |
| Completion | `completion_flow.py` | 保存消息 + 摘要生成 + 流结束 |
| 持久化 | `persistence.py` | AgentRun/AgentStep 数据库操作 |
| 编排者 | `chat_pipeline.py` | 串联各 flow + SSE 包装 |

## 静态检查

### 1. 编译检查（已通过）

```bash
python -m py_compile training_agent/core/chat/chat_pipeline.py
python -m py_compile training_agent/core/chat/routing_flow.py
python -m py_compile training_agent/core/chat/rag_flow.py
python -m py_compile training_agent/core/chat/answer_flow.py
python -m py_compile training_agent/core/chat/autonomous_flow.py
python -m py_compile training_agent/core/chat/finalize_flow.py
python -m py_compile training_agent/core/chat/completion_flow.py
python -m py_compile training_agent/core/chat/artifact_flow.py
python -m py_compile training_agent/core/agent/persistence.py
```

### 2. 边界规则验证（已通过）

- [x] 各 flow 模块不依赖 `ChatRuntimeState`
- [x] 各 flow 模块不依赖 `CurrentUser`
- [x] 各 flow 模块不直接引用数据库
- [x] `ChatRuntimeState` / `CurrentUser` 仅存在于 `chat_pipeline.py`
- [x] 各 flow 使用 frozen dataclass 输入/输出包

### 3. Import 清理（已通过）

- [x] `chat_pipeline.py` 无 `json` import（已移除）
- [x] `persistence.py` 无 `field` import（已移除，实际未使用）
- [x] `artifact_flow.py` 无 `from typing import Any`（已移除，实际未使用）
- [x] `completion_flow.py` 无 `field` import（已移除，实际未使用）
- [x] 各 flow 中保留的 `field` import 均有实际使用

## 运行时冒烟测试

以下测试需启动服务后手动验证：

### A. 普通对话

1. 发送一条简单消息，验证 LLM 流式回答正常
2. 确认 SSE 流完整收到（start → chunks → done）
3. 确认消息被保存到数据库

### B. 知识库问答

1. 向有知识库配置的 Agent 发消息
2. 确认 RAG 检索正常触发
3. 确认回答中包含知识库内容

### C. Agent 工具调用

1. 向配置了工具的 Agent 发指令
2. 确认 autonomous agent 正常执行
3. 确认工具调用结果正确
4. 确认 AgentRun/AgentStep 正常持久化

### D. PPT/PDF 生成

1. 请求 PPT 或 PDF 生成
2. 确认 Artifact 生成流程正常
3. 确认文件生成成功且下载链接有效

### E. Retry 场景

1. 触发需要重试的场景（如超时）
2. 确认 retry 不导致内容重复
3. 确认 finalize 流程正确结束

### F. 路由分发

1. 分别测试纯对话、知识库、Agent 工具、Artifact 生成四种路由
2. 确认 `RequestRouter` 正确分发到对应 flow

## 重构摘要

| 阶段 | Commit | 内容 |
|------|--------|------|
| LLM 配置层修复 | 652b5e4 | Header Prefix / Vision / InstantFileParser / QwenClient |
| LLM 配置层收口 | a7408b6 | 空字符串 / Provider 规范化 / Ollama timeout / Vision 收口 |
| RAG 检索提取 | de7a5f3 | rag_flow.py |
| Agent 持久化提取 | ff63c50 | persistence.py |
| Artifact 生成提取 | 24ed96d | artifact_flow.py |
| 普通回答提取 | 8438fe2 | answer_flow.py |
| Autonomous Agent 提取 | f0a6ccb | autonomous_flow.py |
| Retry/Finalize 提取 | 3f2cd0a | finalize_flow.py |
| Retry 重复修复 | 8b40acb | finalize_flow retry chunk 不再累加到 full_content |
| Completion 提取 | db2f15c | completion_flow.py |
| 路由初始化提取 | 9d02d9e | routing_flow.py |
| Import 清理 | TBD | json/field/Any 清理 + smoke test 文档 |

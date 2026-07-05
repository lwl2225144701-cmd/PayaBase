# Chat Pipeline 拆分后冒烟测试清单

> 拆分后最小回归验证，确保各 flow 模块协作正常。

## 测试环境准备

- 启动本地服务
- 确保数据库已迁移
- 准备一个测试用 Agent（建议配置知识库 + 工具）

---

## 1. 普通聊天

**输入**: `你好`

**预期**:
- 正常流式回答
- `finished: true`
- message 表 assistant 消息已保存
- `context.route` = `"fallback"` 或类似

---

## 2. RAG 问答

**操作**: 选择一个已配置知识库的 Agent，提问相关知识

**预期**:
- `chunks_data` 不为空（召回 chunks）
- `citations` 正常
- `timings.retrieval_ms` 存在
- 回答中包含知识库相关内容

---

## 3. content_generation

**输入**: `帮我写一段产品介绍文案`

**预期**:
- 走 `content_generation` route
- 正常流式输出
- `timings.llm_total_ms` 存在

---

## 4. document_summary

**操作**: 上传一份文档后要求总结

**预期**:
- 走 `document_summary` 或 `rag_qa` route
- 回答正常
- 附件解析正常

---

## 5. PPT 生成

**输入**: `根据资料生成一份 PPT`

**预期**:
- 返回 artifact
- `ppt_task_id` 存在
- `context.artifacts` 包含 PPT 条目

---

## 6. PDF 生成

**输入**: `导出为 PDF`

**预期**:
- 返回 artifact
- `pdf_task_id` 存在
- `context.artifacts` 包含 PDF 条目

---

## 7. autonomous tool mode

**输入**: 需要工具执行的问题（如"搜索最新 AI 资讯"）

**预期**:
- `autonomous_flow` 正常执行
- `tool_trace` 有记录
- `artifact_required` 补偿逻辑不报错
- SSE 流正常结束

---

## 8. KB miss / 联网搜索追问

**操作**: 选择知识库后，问明显不存在于知识库的问题

**预期**:
- `ask_pending` 逻辑正常触发
- 回复"好的"或类似确认后 `web_search_mode=on`
- 后续对话走联网搜索模式

---

## 9. retry / finalize

**操作**: 使用测试标记 `[FORCE_AGENT_STEP1_FAIL]` 触发失败

**预期**:
- 不崩溃
- fallback / retry 行为正常
- `retry_output` 不重复保存

---

## 10. 最终保存检查

**操作**: 每次对话结束后检查 message 表

**预期字段**:
- `assistant message` 已保存
- `context.route` 正常
- `context.agent` 正常（agent_run_id / status / current_step 等）
- `context.artifacts` 正常
- `context.timings.total_ms` 正常（> 0）

---

## 边界规则复查

| 规则 | 状态 |
|------|------|
| flow 文件不含 `StreamingResponse` | ✅ |
| flow 文件不含 `format_sse_chunk` | ✅ |
| flow 文件（除 completion_flow）不含 `save_assistant_message` | ✅ |
| flow 文件（除 persistence）不含 `AgentRun(` / `AgentStep(` / `update(AgentRun)` / `update(AgentStep)` | ✅ |
| flow 文件不含 `db.commit` / `db.rollback` | ✅ |
| flow 文件不含 `ChatRuntimeState` / `CurrentUser` | ✅ |

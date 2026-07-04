# MVP Agent 回归记录模板

## 1. 基础信息
- 测试日期:
- 测试环境:
- 后端地址:
- 测试人:
- 分支/Commit:

## 2. 用例覆盖
- [ ] Case A: 正常问答链路（应完成）
- [ ] Case B: 产物生成链路（PPT/PDF 任务应创建）
- [ ] Case C: 失败重试链路（应触发重试/降级，不应卡死）

## 3. 执行命令
```bash
cd /Users/luweiliang/Downloads/myProject/ai_dify_light
python3 training_agent/scripts/mvp_agent_regression.py \
  --base-url http://127.0.0.1:8123 \
  --token "$MVP_TOKEN" \
  --kb-id "<可选>" \
  --output training_agent/docs/mvp-agent-regression-last.md
```

## 4. 验收标准
1. `chat` 返回完成标记，前端无卡死状态。
2. `AgentRun` 可查，且 `step` 记录完整（至少 step-1 + follow-up step）。
3. 失败场景出现时，`retry` 或 `fallback` 被触发，`last_error` 有分类前缀。
4. `/stats` 中 Agent 指标与趋势可正常加载。

## 5. 结果记录
- Case A 结果:
  - run_id:
  - status:
  - route:
  - steps:
- Case B 结果:
  - run_id:
  - status:
  - artifacts:
  - steps:
- Case C 结果:
  - run_id:
  - status:
  - retry触发:
  - fallback触发:
  - last_error:

## 6. 问题与修复建议
- 问题 1:
- 影响范围:
- 修复建议:

## 7. 结论
- [ ] 本轮通过
- [ ] 本轮不通过
- 说明:


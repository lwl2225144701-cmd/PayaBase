# 整体修复报告

## 背景

本轮处理的重点是两条线：

1. 仅修复涉及到的镜像，避免每次全量重建。
2. 恢复 PDF 任务链路的请求路由与聊天分支，保证单次回归可通过。

## 本次修复内容

### 1. 仅对 `celery-worker` 镜像补充中文字体

修改位置：`training_agent/Dockerfile`

处理方式：

- 只在 `celery-runtime` 阶段增加字体安装，不影响 `api-runtime`、`vectord`、`rerankd`、`searchd`
- 安装 `fonts-wqy-zenhei` 和 `fontconfig`
- 执行 `fc-cache -f`
- apt 源切换为国内镜像

目标：

- 解决 PDF/PPT 生成中可能出现的中文缺字、方块字问题
- 避免每次重建整套镜像

验证：

- 容器内已确认存在 `WenQuanYi Zen Hei`
- `training-celery-worker` 日志未再出现字体相关报错

### 2. 恢复 PDF 路由

修改位置：

- `training_agent/core/agent/request_router.py`
- `training_agent/api/routers/chat.py`

处理方式：

- 在路由器中补充 `PDF_KEYWORDS`
- 增加 `pdf_generation` 路由输出
- 在聊天入口中恢复 `pdf_generation` 分支
- 调用 `build_pdf_generation_prompt`
- 通过 `PDFExportTool` 提交异步 PDF 任务
- 在流式响应中返回 `pdf_task_id`

目标：

- 让“导出 PDF / 生成 PDF”类请求重新进入任务链路
- 保持和 PPT 链路一致的异步任务模式

## 回归结果

### 单次回归

- 后端已按要求重启
- 健康检查通过
- PDF 单次请求已命中任务链路
- 返回 `pdf_task_id=879cbbc9-4cad-4355-94ce-d86963e39923`

### 并发回归

本轮按用户要求未执行并发回归，仅做单轮验证。

## 当前结论

1. 镜像修复范围是收敛的，只动了 `celery-worker` 对应镜像阶段。
2. PDF 路由已恢复，任务链路可以正常提交。
3. 本轮没有引入全量镜像重建。

## 残余风险

1. `PPT` 任务链路受上游 `mimo` 请求超时影响，日志中出现过重试后成功的情况，属于外部依赖波动。
2. 当前 `training_agent/.env` 和 `training_agent/Dockerfile` 仍有既有未提交改动，需要后续按发布节奏统一处理。

## 建议

1. 后续若只修单一任务链路，优先保持镜像阶段隔离，继续采用“只改涉及镜像”的方式。
2. 如果要进一步降低 PDF/PPT 任务波动，再把上游 LLM 超时和重试策略单独收敛。

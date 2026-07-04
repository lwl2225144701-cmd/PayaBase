# Training Agent Backend Deployment Guide

## 1. 部署目标

面向生产环境部署 `training_agent` 后端服务，覆盖：

- API 服务（FastAPI）
- Celery Worker（索引/PPT/PDF 异步任务）
- 基础依赖（PostgreSQL、Redis、MinIO）
- 反向代理（Nginx）

## 2. 架构建议

- `Nginx`：统一入口、TLS、限流、超时与大文件上传控制
- `API`：`uvicorn` 或 `gunicorn + uvicorn workers`
- `Celery Worker`：单独进程组，按队列拆分（可选）
- `PostgreSQL + pgvector`：主库
- `Redis`：Broker + Result backend
- `MinIO`：文档、附件、导出产物存储

## 3. 环境变量矩阵（建议）

按环境维护三套配置：`dev / staging / prod`

- 基础：
  - `postgres_*`, `redis_*`, `minio_*`
- LLM：
  - `llm_provider`, `llm_*`, `llm_chat_*`, `llm_classify_*`, `llm_vision_*`
- 业务：
  - `index_*`, `max_attachment_size`, `temp_attachment_prefix`
- 第三方：
  - `feishu_app_id`, `feishu_app_secret`, `feishu_verification_token`

建议：敏感值通过密钥管理（如 Vault / KMS / CI Secret）注入，不落 Git。

## 4. 首次部署流程

1. 拉取代码并安装依赖

```bash
uv sync --frozen
```

2. 准备 `.env`（生产环境变量）

3. 初始化数据库与结构迁移

```bash
python scripts/init_db.py
```

如你当前版本新增了脚本迁移，额外执行：

- `scripts/migration_add_document_source.sql`
- `scripts/migration_add_platform_adapter.sql`

4. 启动 API 与 Worker

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
celery -A core.tasks worker -l info
```

## 5. Nginx 参考配置（API）

```nginx
server {
    listen 80;
    server_name your-api.example.com;

    client_max_body_size 120m;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 6. 进程管理建议（systemd）

至少拆两类服务：

- `training-agent-api.service`
- `training-agent-worker.service`

关键点：

- `Restart=always`
- 独立日志采集
- 明确 `WorkingDirectory` 与 `.env` 注入

## 7. 灰度发布建议

1. 新版本先部署到 `staging`，执行回归：
   - 登录、KB 查询、文档上传、索引、对话、飞书/Drive 导入
2. 生产采用 `蓝绿` 或 `滚动`：
   - 先切 10% 流量
   - 观察错误率、延迟、任务积压
3. 指标稳定后全量切换

## 8. 回滚策略

代码回滚：

```bash
git checkout <last_stable_tag_or_commit>
```

注意：

- 若数据库有不可逆 DDL，回滚前先评估兼容性
- 推荐“前向修复”优先，避免频繁逆向迁移

## 9. 监控与告警（建议）

- API：QPS、P95、5xx 比例
- Worker：队列长度、任务耗时、失败率、重试次数
- 数据库：连接数、慢查询
- 第三方：LLM 超时、飞书/Drive API 失败率

## 10. 版本发布清单（建议）

每次发版至少确认：

- 迁移脚本是否执行
- `.env` 新增项是否补齐
- API 与前端接口兼容
- 平台回调签名配置是否已生效

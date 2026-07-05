# PayaBase API

个人 AI 知识库助手后端服务，负责知识库管理、文档解析与索引、RAG 检索、对话编排、PPT/PDF 生成、以及多平台消息接入。

## 这个系统做什么

这个后端负责把个人/团队知识资产变成可检索、可对话、可分发的能力。

- 用户上传本地文档，或者导入飞书、Google Drive 文档。
- 系统把文档解析、切分、向量化，写入知识库。
- 用户在前端提问时，系统先做意图判断，再走检索或 Agent 方案生成。
- 生成结果可以继续触发 PPT / PDF 任务，或者通过平台回调接入飞书、微信、QQ。

## 架构是什么

```text
浏览器/平台回调
        |
        v
FastAPI API 层
  |      |       \
  |      |        \-> 平台适配器层（飞书 / 微信 / QQ）
  |      |
  |      +----------> 文档来源层（本地 / 飞书 / Drive）
  |
  +-----------------> 业务服务层（知识库 / 会话 / 用户）
        |
        v
RAG 与任务层
  |      |       \
  |      |        \-> Celery 异步索引 / PPT / PDF
  |      |
  |      +----------> Embedding / Rerank / LLM
  |
  +-----------------> PostgreSQL + pgvector / Redis / MinIO
```

## 业务逻辑是什么

1. 文档进入系统后，先记录元信息，再上传对象存储。
2. 索引任务异步执行：解析文本、提取图片、切块、向量化、入库。
3. 用户提问时，先判定是闲聊、知识问答，还是方案生成。
4. 如果命中知识问答，就走检索增强生成；如果是方案生成，就走 Agent + Tools。
5. 平台回调场景下，消息先通过 Adapter 统一成内部消息，再复用同一套对话和检索逻辑。

## 先看这段（3分钟跑起来）

如果你只想先本地跑通，请直接按下面执行：

```bash
# 1) 进入后端目录
cd training_agent

# 2) 安装依赖
uv sync

# 3) 配置环境变量
cp .env.example .env

# 4) 启动基础依赖（PostgreSQL/Redis/MinIO）
docker compose -f infra/docker-compose.yaml up -d

# 5) 初始化数据库
python scripts/init_db.py

# 6) 启动 API（终端A）
uvicorn api.main:app --reload --host 0.0.0.0 --port 8123

# 7) 启动 Worker（终端B，建议）
celery -A core.tasks worker -l info
```

健康检查：

```bash
curl http://127.0.0.1:8123/health
```

看到 `{"code":200,...}` 或 `status=ok` 就算后端起来了。

## 面向场景

- 个人知识库问答 / 团队知识库问答：基于知识库做检索增强问答。
- 方案/内容生成：在知识检索基础上调用 Agent + Tools 生成方案或内容。
- 多来源知识接入：本地上传、飞书、Google Drive。
- 多平台嵌入：通过 Adapter 模式对接飞书/微信/QQ 回调入口。

## 核心技术栈

- Python 3.12 + FastAPI
- SQLAlchemy 2.x + PostgreSQL + pgvector
- Redis + Celery（异步索引与长任务）
- MinIO（文档与附件对象存储）
- LLM / Embedding / Rerank(可配置 OpenAI 兼容接口)
- **生成模型配置化(策略 + 工厂)**:通过 `LLM_*` / `LLM_CHAT_*` / `LLM_CLASSIFY_*` / `LLM_VISION_*` 切换云端/本地模型,**不改业务代码**

## 目录结构（核心模块）

- `api/routers/`：HTTP 路由层（auth、kb、docs、chat、sources、platform、ppt、pdf）
- `core/rag/`：解析、清洗、分块、检索、图片绑定
- `core/tasks/`：Celery 任务（索引、PPT/PDF 生成）
- `core/sources/`：外部文档源抽象与实现（feishu/google_drive）
- `core/adapters/`：平台消息适配器（feishu/wechat/qq）
- `core/agent/`：意图分类、ReAct Agent 编排
- `models/`：ORM 模型

## Chat Pipeline 拆分说明

`core/chat/` 目录将原先对话主流程拆为职责单一的小模块：

| 文件 | 职责 |
|------|------|
| `chat_pipeline.py` | 主编排：串联各 flow、SSE 包装、状态写回 |
| `routing_flow.py` | 路由决策、AgentRun 初始状态 |
| `rag_flow.py` | RAG 检索（embedding + retriever） |
| `answer_flow.py` | 普通 LLM 回答（内容生成/文档总结/知识问答） |
| `artifact_flow.py` | PPT/PDF 直接生成 |
| `autonomous_flow.py` | Autonomous Agent 工具执行 |
| `finalize_flow.py` | Retry / Finalize 流程 |
| `completion_flow.py` | 收尾保存：消息写入 + context 组装 |
| `persistence.py`（位于 `core/agent/`） | AgentRun / AgentStep 持久化 |

各 flow 模块设计约束：
- 不直接依赖 `ChatRuntimeState` / `CurrentUser`
- 不直接访问数据库（`db.commit` / `db.rollback`）
- 不输出 SSE（由 `chat_pipeline.py` 负责包装）
- 使用 frozen dataclass 输入/输出参数包

## 模型配置化(LLM Factory)

业务层不感知 provider / api_key / base_url / model,统一通过 `core.llm.factory.get_llm_client(purpose)` 获取。

| purpose | 典型用途 | 配置前缀(空 = 跟随 LLM_*) |
|---|---|---|
| `default` | 通用 / 兜底 | `LLM_*` |
| `classify` | 路由、HyDE 摘要、KB 分类 | `LLM_CLASSIFY_*` |
| `chat` | 对话生成、流式输出 | `LLM_CHAT_*` |
| `vision` | 图片解析、文档 OCR | `LLM_VISION_*` |

支持 `provider`:
- `openai`(OpenAI 官方或任何 OpenAI 兼容协议)
- `openai_compatible`(语义同 openai,工厂自动归一)
- `ollama`(本地)

### 场景 A:云端生成 + 本地分类

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

LLM_CLASSIFY_PROVIDER=ollama
LLM_CLASSIFY_BASE_URL=http://localhost:11434
LLM_CLASSIFY_MODEL=qwen2.5:7b

LLM_CHAT_PROVIDER=openai_compatible
LLM_CHAT_API_KEY=sk-xxx
LLM_CHAT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_CHAT_MODEL=qwen-plus
```

### 场景 B:全本地 ollama

```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5:7b
LLM_CHAT_PROVIDER=ollama
LLM_CHAT_BASE_URL=http://localhost:11434
LLM_CHAT_MODEL=qwen2.5:7b
LLM_CLASSIFY_PROVIDER=ollama
LLM_CLASSIFY_BASE_URL=http://localhost:11434
LLM_CLASSIFY_MODEL=qwen2.5:7b
```

切换模型时:**只改 .env,不动业务代码、不重启策略层**(`get_llm_client` 内部按 `(purpose, timeout)` 缓存,改完调用 `core.llm.factory.clear_llm_client_cache()` 立即生效)。
- `scripts/`：初始化与迁移脚本

## 启动流程（本地开发）

1. 前置条件检查

```bash
python3 --version   # 建议 3.12.x
docker --version
docker compose version
uv --version
```

2. 安装依赖

```bash
uv sync
```

3. 准备环境变量

```bash
cp .env.example .env
```

最低可运行需要确认这些值（`.env`）：

- `POSTGRES_*`
- `REDIS_*`
- `MINIO_*`
- `JWT_SECRET`
- `LLM_PROVIDER` + `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL`

4. 启动基础依赖（Postgres/Redis/MinIO 等）

```bash
docker compose -f infra/docker-compose.yaml up -d
```

5. 初始化数据库

```bash
python scripts/init_db.py
```

6. 启动 API

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8123
```

7. 启动 Celery Worker（推荐，文档索引/PPT/PDF 需要）

```bash
celery -A core.tasks worker -l info
```

8. 验证关键链路

```bash
# 健康检查
curl http://127.0.0.1:8123/health
```

## 关键能力说明

- 文档入库链路：`upload -> parse -> chunk -> embed -> batch insert -> ready`
- 来源透传：`source_type/source_url` 会进入文档与 chunk metadata
- 飞书深度解析：表格转 Markdown、复杂表格降级展开、图片下载 + Vision 文本注入 + MinIO 绑定
- 平台回调：`/api/platform/{platform}/callback` 统一入口，适配器负责验签/解析/回发

## 主要接口分组

- 认证与用户：`/api/auth/*`
- 知识库与文档：`/api/kb/*`、`/api/kb/{kb_id}/docs/*`
- 外部来源接入：`/api/sources/*`
- 对话：`/api/conversations/*`
- 平台回调：`/api/platform/{platform}/callback`
- 任务生成：`/api/ppt/*`、`/api/pdf/*`

## 迁移提示

本仓库新增过多份 SQL 迁移脚本（如 `scripts/migration_add_platform_adapter.sql`、`scripts/migration_add_document_source.sql`）。  
部署到新环境时，请确保这些结构变更与当前模型同步执行。

## 常见问题排查（新同学高频）

1. `数据库连接失败`
- 先看容器是否在跑：`docker ps`
- 检查 `.env` 的 `POSTGRES_HOST/PORT/USER/PASSWORD/DB`

2. `上传文档后一直 pending`
- 大概率 Worker 没启动：执行 `celery -A core.tasks worker -l info`
- 检查 Redis 是否可连通

3. `LLM 调用超时或 401`
- 检查 `LLM_*` 配置是否正确
- 内网模型时确认 `LLM_BASE_URL` 可访问

4. `飞书导入失败`
- 检查 `FEISHU_APP_ID/FEISHU_APP_SECRET/FEISHU_VERIFICATION_TOKEN`
- 回调地址和飞书后台配置要一致

## 推荐实践（建议）

- 生产环境把平台签名校验改为严格模式（当前微信/QQ 适配器为占位实现）。
- 将 `.env` 中的模型、超时、provider 参数按环境分层（dev/staging/prod）。
- 对平台回调增加幂等监控和告警（`platform_message_receipts`）。
